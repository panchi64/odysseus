"""The corpus capability: chunk-store seal, folder crawl/idempotency, fused retrieve."""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

import numpy as np
import pytest
from sqlmodel import Session, select

from core.db import init_db, make_engine
from core.exceptions import NotFoundError
from core.vault import Vault
from models.corpus import CorpusChunk
from services import ranking
from services.corpus.chunk_store import CorpusChunkStore, content_hash
from services.corpus.folder import FolderAdapter
from services.corpus.index import CorpusIndex
from services.corpus.wrappers import MemoryAdapter
from services.memory import MemoryStore

from .test_memory import DegradedEmbedder, FakeEmbedder

OWNER = "operator"


def _index(embedder, chunk_store, folder):
    """A CorpusIndex without a real registry (stats aren't under test here)."""
    from services.registry import ModelRegistry

    return CorpusIndex(embedder, ModelRegistry.__new__(ModelRegistry), chunk_store, folder)


async def _engine_vault(embedder):
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    vault = Vault(Path(tempfile.mkdtemp()) / "keyfile.json")
    await vault.setup("pw")
    return engine, vault


# --- chunk store: encryption at rest --------------------------------------


async def test_chunk_text_and_vector_sealed_at_rest():
    embedder = FakeEmbedder()
    engine, vault = await _engine_vault(embedder)
    store = CorpusChunkStore(engine, vault, embedder)
    from services.chunking import chunk_text

    await store.upsert(OWNER, "folder", "src-1", "/notes/a.txt", chunk_text("the cat is here"))
    await store.reembed(OWNER, "src-1", current_model="fake-embed")

    with Session(engine) as session:
        row = session.exec(select(CorpusChunk)).one()
    assert "cat" not in row.text_enc  # text is sealed
    assert row.embedding_enc is not None and "1.0" not in row.embedding_enc  # vector sealed
    # And it round-trips through the vault.
    assert vault.decrypt_str(row.text_enc) == "the cat is here"


# --- folder adapter: crawl, idempotency, missing path ----------------------


async def _folder(tmp: Path, embedder):
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    vault = Vault(Path(tempfile.mkdtemp()) / "keyfile.json")
    await vault.setup("pw")
    chunk_store = CorpusChunkStore(engine, vault, embedder)
    adapter = FolderAdapter(engine, chunk_store, vault.unlocked_event)
    return engine, vault, chunk_store, adapter


async def test_folder_crawls_chunks_and_embeds(tmp_path: Path):
    (tmp_path / "a.txt").write_text("I have a pet cat at home")
    (tmp_path / "b.md").write_text("My commute uses a car")
    (tmp_path / "skip.bin").write_text("ignored binary")

    engine, _vault, chunk_store, adapter = await _folder(tmp_path, FakeEmbedder())
    await adapter.start()
    source = await adapter.add_folder(OWNER, str(tmp_path))
    await adapter._worker.join()  # drain the queued crawl
    await adapter.stop()

    assert await chunk_store.count(OWNER, source.id) == 2  # two text files, binary skipped
    statuses = await adapter.status(OWNER)
    assert statuses[0].status == "indexed"


async def test_folder_reindex_is_idempotent(tmp_path: Path):
    (tmp_path / "a.txt").write_text("a stable note about a dog")
    engine, _vault, chunk_store, adapter = await _folder(tmp_path, FakeEmbedder())
    await adapter.start()
    source = await adapter.add_folder(OWNER, str(tmp_path))
    await adapter._worker.join()
    first = await chunk_store.count(OWNER, source.id)

    await adapter.rebuild(OWNER, source.id)  # re-crawl identical content
    await adapter._worker.join()
    await adapter.stop()
    # No dup rows — content hash dedups the unchanged file.
    assert await chunk_store.count(OWNER, source.id) == first


async def test_missing_path_marks_error_status(tmp_path: Path):
    engine, _vault, chunk_store, adapter = await _folder(tmp_path, FakeEmbedder())
    await adapter.start()
    source = await adapter.add_folder(OWNER, str(tmp_path / "does-not-exist"))
    await adapter._worker.join()
    await adapter.stop()

    statuses = await adapter.status(OWNER)
    row = next(s for s in statuses if s.source_id == source.id)
    assert row.status == "error"
    assert row.error_hint == "PATH NOT FOUND"


# --- index: fan-out + RRF across sources -----------------------------------


async def _memory_store(embedder):
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    vault = Vault(Path(tempfile.mkdtemp()) / "keyfile.json")
    await vault.setup("pw")
    return MemoryStore(engine, vault, embedder)


async def test_retrieve_fuses_folder_and_memory(tmp_path: Path):
    (tmp_path / "doc.txt").write_text("the feline sleeps all day")
    embedder = FakeEmbedder()
    engine, vault, chunk_store, folder = await _folder(tmp_path, embedder)
    await folder.start()
    src = await folder.add_folder(OWNER, str(tmp_path))
    await folder._worker.join()

    memory = MemoryStore(engine, vault, embedder)
    await memory.remember(OWNER, "I drive a car to work")

    from services.registry import ModelRegistry

    index = CorpusIndex(embedder, ModelRegistry.__new__(ModelRegistry), chunk_store, folder)
    index.register(folder)
    index.register(MemoryAdapter(memory))

    # "cat" embeds into the same concept slot as "feline" (the fake concept space),
    # so the folder hit surfaces by meaning across sources.
    hits = await index.retrieve(OWNER, "cat", limit=5)
    await folder.stop()
    assert hits, "the corpus should retrieve across folder + memory"
    assert any(h.source_id == src.id for h in hits)
    assert all(h.matched_by in ("semantic", "keyword", "both") for h in hits)


async def test_retrieve_degrades_to_sparse_without_embeddings(tmp_path: Path):
    (tmp_path / "doc.txt").write_text("the wifi password is hunter2")
    engine, vault, chunk_store, folder = await _folder(tmp_path, DegradedEmbedder())
    await folder.start()
    await folder.add_folder(OWNER, str(tmp_path))
    await folder._worker.join()

    from services.registry import ModelRegistry

    index = CorpusIndex(
        DegradedEmbedder(), ModelRegistry.__new__(ModelRegistry), chunk_store, folder
    )
    index.register(folder)

    hits = await index.retrieve(OWNER, "wifi password", limit=5)
    await folder.stop()
    assert hits and hits[0].matched_by == "keyword"


def test_content_hash_is_stable():
    assert content_hash("abc") == content_hash("abc")
    assert content_hash("abc") != content_hash("abd")


def test_rrf_fuses_cross_source_ranks():
    # The fusion primitive the index reuses is rank-based, so two sources' scores
    # combine without normalization — a sanity check the index relies on.
    fused = ranking.rrf({"a:1": 0.9, "b:1": 0.1}, {"b:1": 5.0})
    assert fused["b:1"] > 0  # surfaced by sparse despite a weak dense score
    assert np.isfinite(fused["a:1"])


# --- regression: cross-source fusion is rank-based, not raw-score ----------


async def test_strong_memory_hit_not_buried_under_folder_hits(tmp_path: Path):
    """A perfect semantic memory match must survive next to many folder hits whose
    raw cosines dwarf memory's (much smaller) fused score. The old fusion merged both
    sources into one score map and ranked by value, sinking the memory hit below every
    folder cosine; rank-based fusion gives each source's top hit equal standing."""
    embedder = FakeEmbedder()
    # Five folder docs that each match "cat" by both meaning and keyword (cosine ~1).
    for i in range(5):
        (tmp_path / f"doc{i}.txt").write_text("the cat naps in the sun")
    engine, vault, chunk_store, folder = await _folder(tmp_path, embedder)
    await folder.start()
    await folder.add_folder(OWNER, str(tmp_path))
    await folder._worker.join()

    # One memory that matches "cat" only by meaning (no literal "cat" token).
    memory = MemoryStore(engine, vault, embedder)
    await memory.remember(OWNER, "a fluffy feline that purrs")

    index = _index(embedder, chunk_store, folder)
    index.register(folder)
    index.register(MemoryAdapter(memory))

    hits = await index.retrieve(OWNER, "cat", limit=3)
    # The memory hit lands in the top results rather than being buried by raw cosine.
    assert any(h.source_id == MemoryAdapter.SOURCE_ID for h in hits)


# --- regression: per-source reindex routing --------------------------------


async def test_reindex_unknown_source_raises(tmp_path: Path):
    embedder = FakeEmbedder()
    _engine, _vault, chunk_store, folder = await _folder(tmp_path, embedder)
    index = _index(embedder, chunk_store, folder)
    index.register(folder)
    with pytest.raises(NotFoundError):
        await index.reindex(OWNER, "no-such-source")


async def test_reindex_surface_routes_to_its_adapter(tmp_path: Path):
    embedder = FakeEmbedder()
    engine, vault, chunk_store, folder = await _folder(tmp_path, embedder)
    memory = MemoryStore(engine, vault, embedder)
    index = _index(embedder, chunk_store, folder)
    index.register(folder)
    index.register(MemoryAdapter(memory))
    # A surface id routes to that adapter's reindex (memory re-embed) — no raise, no
    # folder fallback. Empty store ⇒ zero rows healed.
    assert await index.reindex(OWNER, MemoryAdapter.SOURCE_ID) == 0


# --- regression: EMB-2 segregation + heal for corpus chunks ----------------


async def test_chunks_segregate_then_reembed_heals_on_model_change(tmp_path: Path):
    from services.chunking import chunk_text

    engine, vault, chunk_store, _folder_adapter = await _folder(tmp_path, FakeEmbedder())
    store = CorpusChunkStore(engine, vault, FakeEmbedder(model="model-a"))
    await store.upsert(OWNER, "folder", "src-1", "/n/a.txt", chunk_text("a fluffy feline"))
    await store.reembed(OWNER, "src-1", current_model="model-a")

    # The operator switched embedding models; query vectors now live in model-b's space.
    batch = await FakeEmbedder(model="model-b").embed(OWNER, ["cat"])
    qvec, qtokens = np.asarray(batch.vectors[0]), {"cat"}

    store_b = CorpusChunkStore(engine, vault, FakeEmbedder(model="model-b"))
    before = await store_b.retrieve(OWNER, "folder", qvec, "model-b", qtokens, limit=5)
    assert all(h.matched_by != "semantic" for h in before)  # segregated: no dense match

    healed = await store_b.reembed(OWNER, "src-1", current_model="model-b")
    assert healed == 1
    after = await store_b.retrieve(OWNER, "folder", qvec, "model-b", qtokens, limit=5)
    assert any(h.dense_score is not None for h in after)  # meaning-recall restored


# --- regression: lock-aware indexing parks while the vault is locked --------


async def test_folder_index_parks_while_vault_locked(tmp_path: Path):
    (tmp_path / "a.txt").write_text("a note about a dog")
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    vault = Vault(Path(tempfile.mkdtemp()) / "keyfile.json")
    chunk_store = CorpusChunkStore(engine, vault, FakeEmbedder())
    adapter = FolderAdapter(engine, chunk_store, vault.unlocked_event)

    # Register while unlocked — the source's own host path is sealed now (`XC-SEC-3`), so
    # registering needs the key. That's not a new constraint in practice: the only caller
    # is the /corpus route, and the auth gate in front of it implies an unlocked vault.
    # Then lock, and only then start the worker: the queued crawl is what must park.
    await vault.setup("pw")
    source = await adapter.add_folder(OWNER, str(tmp_path))  # sealed row + queued job
    vault.lock()

    await adapter.start()
    await asyncio.sleep(0.05)  # give the worker a chance — it should park, not index
    assert await chunk_store.count(OWNER, source.id) == 0  # nothing sealed while locked

    assert await vault.unlock("pw")  # unlock ⇒ the parked worker resumes
    await asyncio.wait_for(adapter._worker.join(), timeout=5)
    await adapter.stop()
    assert await chunk_store.count(OWNER, source.id) == 1


# --- regression: symlinked file escaping the tree is skipped ----------------


async def test_symlinked_file_outside_tree_is_skipped(tmp_path: Path):
    (tmp_path / "real.txt").write_text("inside the tree about a cat")
    outside = Path(tempfile.mkdtemp()) / "secret.txt"
    outside.write_text("outside secret about a dog")
    os.symlink(outside, tmp_path / "link.txt")  # escapes the indexed tree

    engine, vault, chunk_store, adapter = await _folder(tmp_path, FakeEmbedder())
    await adapter.start()
    source = await adapter.add_folder(OWNER, str(tmp_path))
    await adapter._worker.join()
    await adapter.stop()

    assert await chunk_store.count(OWNER, source.id) == 1  # only real.txt, not the symlink
    with Session(engine) as session:
        texts = [vault.decrypt_str(row.text_enc) for row in session.exec(select(CorpusChunk)).all()]
    assert any("inside the tree" in t for t in texts)  # the real file was indexed
    assert not any("secret" in t for t in texts)  # external content never ingested
