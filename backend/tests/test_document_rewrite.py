"""The two *applied* halves of `DOC-3` — a full rewrite and a targeted edit — still behave
now that proposing sits beside them. Both write immediately, both mint an ``ai``-origin
version, and a targeted edit still refuses an ambiguous or absent span."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from core.db import init_db, make_engine
from core.exceptions import DocumentSpanError
from core.vault import Vault
from models.document import DocumentVersionOrigin
from services.documents import DocumentStore

OWNER = "operator"


class _RecordingAdapter:
    def __init__(self) -> None:
        self.indexed: list[tuple[str, str]] = []

    def index_document(self, owner_id: str, document_id: str, body: str) -> None:
        self.indexed.append((document_id, body))

    def remove_document(self, owner_id: str, document_id: str) -> None: ...


async def _store() -> tuple[DocumentStore, _RecordingAdapter]:
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    vault = Vault(Path(tempfile.mkdtemp()) / "keyfile.json")
    await vault.setup("pw")
    adapter = _RecordingAdapter()
    return DocumentStore(engine, vault, adapter), adapter


async def test_full_rewrite_replaces_the_body_and_records_an_ai_version():
    store, adapter = await _store()
    doc = await store.create(OWNER, "Draft", "# Old\n\nthe first draft\n")
    adapter.indexed.clear()

    view, version = await store.edit(
        OWNER,
        doc.id,
        body="# New\n\na completely different draft\n",
        origin=DocumentVersionOrigin.AI,
    )

    assert view.body == "# New\n\na completely different draft\n"
    assert version == 2
    versions = await store.list_versions(OWNER, doc.id)
    assert [(v.version, v.origin) for v in versions] == [(2, "ai"), (1, "user")]
    # Version 1 still holds the pre-rewrite text — a rewrite is restorable like any change.
    assert versions[1].body == "# Old\n\nthe first draft\n"
    assert adapter.indexed == [(doc.id, view.body)]


async def test_targeted_edit_changes_one_span_and_leaves_the_rest_byte_identical():
    store, adapter = await _store()
    body = "Intro paragraph.\n\nThe meeting is on Tuesday.\n\nOutro paragraph.\n"
    doc = await store.create(OWNER, "Notes", body)
    adapter.indexed.clear()

    view, version, created_at = await store.replace_span(OWNER, doc.id, "on Tuesday", "on Thursday")

    assert view.body == body.replace("on Tuesday", "on Thursday")
    assert view.body.startswith("Intro paragraph.") and view.body.endswith("Outro paragraph.\n")
    assert version == 2 and created_at is not None
    assert (await store.list_versions(OWNER, doc.id))[0].origin == "ai"
    assert adapter.indexed == [(doc.id, view.body)]


async def test_a_targeted_edit_refuses_an_absent_or_ambiguous_span():
    store, _ = await _store()
    doc = await store.create(OWNER, "Notes", "repeat\nrepeat\n")

    with pytest.raises(DocumentSpanError) as absent:
        await store.replace_span(OWNER, doc.id, "missing", "x")
    assert absent.value.occurrences == 0

    with pytest.raises(DocumentSpanError) as ambiguous:
        await store.replace_span(OWNER, doc.id, "repeat", "x")
    assert ambiguous.value.occurrences == 2

    # A refused edit is a no-op: no write, no version.
    assert (await store.get(OWNER, doc.id)).body == "repeat\nrepeat\n"
    assert [v.version for v in await store.list_versions(OWNER, doc.id)] == [1]


async def test_rewrite_and_targeted_edit_stack_into_one_restorable_history():
    store, _ = await _store()
    doc = await store.create(OWNER, "Plan", "step one\nstep two\n")

    await store.edit(OWNER, doc.id, body="phase one\nphase two\n", origin=DocumentVersionOrigin.AI)
    await store.replace_span(OWNER, doc.id, "phase two", "phase two (revised)")

    assert (await store.get(OWNER, doc.id)).body == "phase one\nphase two (revised)\n"
    assert [v.version for v in await store.list_versions(OWNER, doc.id)] == [3, 2, 1]

    restored = await store.restore_version(OWNER, doc.id, 1)
    assert restored.body == "step one\nstep two\n"
    # Restoring appends rather than rewinding — the history stays append-only.
    assert [v.version for v in await store.list_versions(OWNER, doc.id)] == [4, 3, 2, 1]
