"""The documents corpus adapter: index/clear/retrieve, the edit-clears-stale deviation."""

from __future__ import annotations

import tempfile
from pathlib import Path

from core.db import init_db, make_engine
from core.vault import Vault
from services.corpus.chunk_store import CorpusChunkStore
from services.corpus.documents import DocumentsAdapter
from services.documents import DocumentStore

from .test_memory import FakeEmbedder

OWNER = "operator"


async def _store():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    vault = Vault(Path(tempfile.mkdtemp()) / "keyfile.json")
    await vault.setup("pw")
    chunk_store = CorpusChunkStore(engine, vault, FakeEmbedder())
    adapter = DocumentsAdapter(engine, chunk_store, vault.unlocked_event)
    await adapter.start()
    store = DocumentStore(engine, vault, adapter)
    return chunk_store, adapter, store


async def _retrieve(adapter, token: str):
    """Keyword-only recall (deterministic): no query vector, one query token."""
    return await adapter.retrieve(OWNER, token, None, None, {token}, limit=5)


async def test_create_indexes_body_into_documents_kind():
    chunk_store, adapter, store = await _store()
    doc = await store.create(OWNER, "Notes", "the operator keeps a pet cat")
    await adapter._worker.join()
    await adapter.stop()

    assert await chunk_store.count(OWNER, doc.id) == 1
    hits = await _retrieve(adapter, "cat")
    assert hits and hits[0].source_id == doc.id


async def test_edit_clears_stale_chunks_no_orphans():
    """The one deviation from the folder source: an edit must clear before re-inserting,
    so text removed by the edit leaves no orphan chunk behind."""
    chunk_store, adapter, store = await _store()
    doc = await store.create(OWNER, "Notes", "alpha unique marker")
    await adapter._worker.join()
    await store.edit(OWNER, doc.id, body="beta different marker")
    await adapter._worker.join()
    await adapter.stop()

    assert await chunk_store.count(OWNER, doc.id) == 1  # not 2 — the old chunk is gone
    assert not await _retrieve(adapter, "alpha")  # removed text no longer retrievable
    assert await _retrieve(adapter, "beta")  # current text is


async def test_reindex_same_body_is_idempotent():
    chunk_store, adapter, store = await _store()
    doc = await store.create(OWNER, "Notes", "a stable note")
    await adapter._worker.join()
    adapter.index_document(OWNER, doc.id, "a stable note")  # same content again
    await adapter._worker.join()
    await adapter.stop()
    assert await chunk_store.count(OWNER, doc.id) == 1


async def test_archive_removes_chunks_from_retrieval():
    chunk_store, adapter, store = await _store()
    doc = await store.create(OWNER, "Notes", "the wifi password is hunter2")
    await adapter._worker.join()
    await store.archive(OWNER, doc.id)
    await adapter._worker.join()
    await adapter.stop()

    assert await chunk_store.count(OWNER, doc.id) == 0
    assert not await _retrieve(adapter, "hunter2")


async def test_count_items_counts_documents_not_chunks():
    chunk_store, adapter, store = await _store()
    long_body = " ".join(f"word{i}" for i in range(600))  # > one chunk window
    doc = await store.create(OWNER, "Long", long_body)
    await adapter._worker.join()
    await adapter.stop()
    assert await chunk_store.count(OWNER, doc.id) >= 2  # split into multiple chunks
    assert await chunk_store.count_items(OWNER, "documents") == 1  # but one document


async def test_status_reports_indexed_document_count():
    chunk_store, adapter, store = await _store()
    await store.create(OWNER, "A", "first document")
    await store.create(OWNER, "B", "second document")
    await adapter._worker.join()
    status = await adapter.status(OWNER)
    await adapter.stop()

    assert status.source_id == "surf-documents"
    assert status.kind == "surface"
    assert status.status == "indexed"
    assert status.doc_count == 2  # two distinct documents indexed
