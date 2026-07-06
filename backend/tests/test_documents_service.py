"""The documents capability: CRUD, versioning, archive/restore, at-rest sealing."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from sqlmodel import Session, select

from core.db import init_db, make_engine
from core.exceptions import DocumentSpanError, NotFoundError
from core.vault import Vault
from models.document import Document
from services.corpus.chunk_store import CorpusChunkStore
from services.corpus.documents import DocumentsAdapter
from services.documents import DocumentStore, detect_type_language

from .test_memory import FakeEmbedder

OWNER = "operator"


async def _store(embedder=None):
    """A started DocumentStore + its adapter over a throwaway in-memory DB."""
    embedder = embedder or FakeEmbedder()
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    vault = Vault(Path(tempfile.mkdtemp()) / "keyfile.json")
    await vault.setup("pw")
    chunk_store = CorpusChunkStore(engine, vault, embedder)
    adapter = DocumentsAdapter(engine, chunk_store, vault.unlocked_event)
    await adapter.start()
    store = DocumentStore(engine, vault, adapter)
    return engine, vault, chunk_store, adapter, store


class _RecordingAdapter:
    """A stand-in adapter that records the store's index/remove calls (duck-typed)."""

    def __init__(self) -> None:
        self.indexed: list[tuple[str, str]] = []
        self.removed: list[str] = []

    def index_document(self, owner_id: str, document_id: str, body: str) -> None:
        self.indexed.append((document_id, body))

    def remove_document(self, owner_id: str, document_id: str) -> None:
        self.removed.append(document_id)


async def _store_recording():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    vault = Vault(Path(tempfile.mkdtemp()) / "keyfile.json")
    await vault.setup("pw")
    adapter = _RecordingAdapter()
    return adapter, DocumentStore(engine, vault, adapter)


# --- versioning (DOC-2) ----------------------------------------------------


async def test_create_records_first_user_version():
    _engine, _vault, _chunks, adapter, store = await _store()
    doc = await store.create(OWNER, "Notes", "the body")
    await adapter.stop()

    versions = await store.list_versions(OWNER, doc.id)
    assert len(versions) == 1
    assert versions[0].version == 1
    assert versions[0].origin == "user"
    assert versions[0].body == "the body"


async def test_edit_appends_version_and_bumps_updated_at():
    _engine, _vault, _chunks, adapter, store = await _store()
    doc = await store.create(OWNER, "Notes", "first")
    edited, version = await store.edit(OWNER, doc.id, body="second")
    await adapter.stop()

    versions = await store.list_versions(OWNER, doc.id)
    assert [v.version for v in versions] == [2, 1]  # newest first
    assert version == 2
    assert edited.updated_at >= doc.updated_at
    assert edited.body == "second"


async def test_restore_version_reverts_and_appends_a_version():
    _engine, _vault, _chunks, adapter, store = await _store()
    doc = await store.create(OWNER, "Notes", "original")
    await store.edit(OWNER, doc.id, body="changed")
    restored = await store.restore_version(OWNER, doc.id, 1)
    await adapter.stop()

    assert restored.body == "original"  # content reverted
    versions = await store.list_versions(OWNER, doc.id)
    # History stays append-only: v1 original, v2 changed, v3 the restore.
    assert [v.version for v in versions] == [3, 2, 1]
    assert versions[0].body == "original"


async def test_restore_unknown_version_raises():
    _engine, _vault, _chunks, adapter, store = await _store()
    doc = await store.create(OWNER, "Notes", "body")
    await adapter.stop()
    with pytest.raises(NotFoundError):
        await store.restore_version(OWNER, doc.id, 99)


# --- archive / restore + listing (DOC-1) -----------------------------------


async def test_archive_hides_from_default_list_and_restore_brings_back():
    _engine, _vault, _chunks, adapter, store = await _store()
    doc = await store.create(OWNER, "Notes", "body")
    await store.archive(OWNER, doc.id)
    await adapter.stop()

    assert [d.id for d in await store.list_documents(OWNER)] == []
    archived = await store.list_documents(OWNER, include_archived=True)
    assert [d.id for d in archived] == [doc.id] and archived[0].archived is True

    restored = await store.restore(OWNER, doc.id)
    assert restored.archived is False
    assert [d.id for d in await store.list_documents(OWNER)] == [doc.id]


async def test_count_excludes_archived():
    _engine, _vault, _chunks, adapter, store = await _store()
    a = await store.create(OWNER, "A", "x")
    await store.create(OWNER, "B", "y")
    await store.archive(OWNER, a.id)
    await adapter.stop()
    assert await store.count(OWNER) == 1


# --- owner guard + at-rest sealing -----------------------------------------


async def test_owner_guard_raises_not_found():
    _engine, _vault, _chunks, adapter, store = await _store()
    doc = await store.create(OWNER, "Notes", "body")
    await adapter.stop()
    with pytest.raises(NotFoundError):
        await store.get("someone-else", doc.id)


async def test_title_and_body_sealed_at_rest():
    engine, vault, _chunks, adapter, store = await _store()
    await store.create(OWNER, "SecretTitle", "the wifi password is hunter2")
    await adapter.stop()

    with Session(engine) as session:
        row = session.exec(select(Document)).one()
    assert "SecretTitle" not in row.title_enc
    assert "hunter2" not in row.body_enc
    assert vault.decrypt_str(row.body_enc) == "the wifi password is hunter2"


# --- type / language detection ---------------------------------------------


async def test_title_only_edit_skips_reindex():
    adapter, store = await _store_recording()
    doc = await store.create(OWNER, "Notes", "the body text")
    assert len(adapter.indexed) == 1  # create indexed the body
    await store.edit(OWNER, doc.id, title="New Title")  # title only
    assert len(adapter.indexed) == 1  # body unchanged → no re-index
    await store.edit(OWNER, doc.id, body="a new body")  # body changed
    assert len(adapter.indexed) == 2  # re-indexed


async def test_list_returns_summaries_without_body():
    _engine, _vault, _chunks, adapter, store = await _store()
    await store.create(OWNER, "Notes", "first line here\nsecond line follows")
    await adapter.stop()
    rows = await store.list_documents(OWNER)
    assert rows[0].snippet == "first line here"
    assert rows[0].word_count == 6
    assert not hasattr(rows[0], "body")  # full body never leaves the store for a list


# --- conversation scoping (chat View seam) ---------------------------------


async def test_list_by_conversation_filters_by_thread_and_archived():
    _engine, _vault, _chunks, adapter, store = await _store()
    a = await store.create(OWNER, "A", "x", conversation_id="c1")
    await store.create(OWNER, "B", "y", conversation_id="c2")  # other thread
    await store.create(OWNER, "C", "z")  # library doc (no conversation)
    gone = await store.create(OWNER, "D", "w", conversation_id="c1")
    await store.archive(OWNER, gone.id)
    await adapter.stop()

    rows = await store.list_by_conversation(OWNER, "c1")
    assert [r.id for r in rows] == [a.id]  # only the active c1 doc
    assert rows[0].conversation_id == "c1"


async def test_list_user_edited_returns_only_docs_the_operator_last_touched():
    _engine, _vault, _chunks, adapter, store = await _store()
    # Agent-authored doc, no operator edit — the model already knows it, so it's excluded.
    ai = await store.create(OWNER, "AI", "agent text", conversation_id="c1", origin="ai")
    # Agent authored, then the operator edited it — included (its latest version is theirs).
    edited = await store.create(OWNER, "Edited", "v1", conversation_id="c1", origin="ai")
    await store.edit(OWNER, edited.id, body="operator text", origin="user")
    # Other thread — excluded even though operator-authored.
    await store.create(OWNER, "Other", "x", conversation_id="c2", origin="user")
    await adapter.stop()

    rows = await store.list_user_edited(OWNER, "c1")
    assert [r.id for r in rows] == [edited.id]
    assert rows[0].body == "operator text"
    assert ai  # present in the thread but not surfaced (latest version is the agent's)


async def test_replace_span_edits_uniquely_and_returns_the_new_version():
    _engine, _vault, _chunks, adapter, store = await _store()
    doc = await store.create(OWNER, "A", "hello world", origin="ai")
    view, version = await store.replace_span(OWNER, doc.id, "world", "there", origin="ai")
    assert view.body == "hello there" and version == 2

    with pytest.raises(DocumentSpanError) as absent:
        await store.replace_span(OWNER, doc.id, "zzz", "!", origin="ai")
    assert absent.value.occurrences == 0

    await store.edit(OWNER, doc.id, body="la la la", origin="ai")
    with pytest.raises(DocumentSpanError) as ambiguous:
        await store.replace_span(OWNER, doc.id, "la", "LA", origin="ai")
    assert ambiguous.value.occurrences == 3
    await adapter.stop()


def test_detect_type_language_classifies_structure():
    assert detect_type_language("# Heading\n\nsome prose")[0] == "markdown"
    assert detect_type_language("def f():\n    return 1")[0] == "code"
    assert detect_type_language("just a plain sentence")[0] == "text"
    # Language is best-effort and degrades to None on empty/whitespace input.
    assert detect_type_language("   ")[1] is None
