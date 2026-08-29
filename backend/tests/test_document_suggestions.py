"""The suggestion lifecycle (`DOC-3`): a proposed change is inert until the operator
accepts it, accepting is the only path that mints a version, and a suggestion whose anchor
has moved refuses instead of corrupting the document."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from core.db import init_db, make_engine
from core.exceptions import DocumentSpanError, NotFoundError
from core.vault import Vault
from services.document_suggestions import ProposedChange, stream_preview
from services.documents import DocumentStore

OWNER = "operator"


class _RecordingAdapter:
    """A duck-typed corpus adapter that records the store's index/remove calls."""

    def __init__(self) -> None:
        self.indexed: list[tuple[str, str]] = []
        self.removed: list[str] = []

    def index_document(self, owner_id: str, document_id: str, body: str) -> None:
        self.indexed.append((document_id, body))

    def remove_document(self, owner_id: str, document_id: str) -> None:
        self.removed.append(document_id)


async def _store() -> tuple[DocumentStore, _RecordingAdapter]:
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    vault = Vault(Path(tempfile.mkdtemp()) / "keyfile.json")
    await vault.setup("pw")
    adapter = _RecordingAdapter()
    return DocumentStore(engine, vault, adapter), adapter


BODY = "Alpha line.\nBeta line.\nGamma line.\n"


async def _doc(store: DocumentStore, body: str = BODY) -> str:
    view = await store.create(OWNER, "Notes", body)
    return view.id


# --- a proposal changes nothing ------------------------------------------


async def test_proposing_leaves_the_document_and_its_history_untouched():
    store, adapter = await _store()
    doc_id = await _doc(store)
    adapter.indexed.clear()

    proposed = await store.suggestions.propose(
        OWNER,
        doc_id,
        [
            ProposedChange("Alpha line.", "Alpha line, revised.", "clearer"),
            ProposedChange("Gamma line.", "Gamma line, revised."),
        ],
        summary="tightened two lines",
        conversation_id="conv-1",
    )

    assert len(proposed.changes) == 2 and proposed.pending == 2
    assert proposed.summary == "tightened two lines"
    assert [c.ordinal for c in proposed.changes] == [0, 1]
    assert all(c.status == "pending" and c.version is None for c in proposed.changes)

    # The document is byte-identical and no version was minted.
    assert (await store.get(OWNER, doc_id)).body == BODY
    assert [v.version for v in await store.list_versions(OWNER, doc_id)] == [1]
    # Nothing was re-indexed either — the corpus still holds the unchanged body.
    assert adapter.indexed == []


async def test_a_proposal_with_a_bad_anchor_is_refused_whole():
    store, _ = await _store()
    doc_id = await _doc(store, "repeat\nrepeat\n")

    with pytest.raises(DocumentSpanError) as absent:
        await store.suggestions.propose(OWNER, doc_id, [ProposedChange("nope", "x")])
    assert absent.value.occurrences == 0

    with pytest.raises(DocumentSpanError) as ambiguous:
        await store.suggestions.propose(OWNER, doc_id, [ProposedChange("repeat", "x")])
    assert ambiguous.value.occurrences == 2

    # One bad change refuses the whole set — nothing partial is recorded.
    with pytest.raises(DocumentSpanError):
        await store.suggestions.propose(
            OWNER,
            doc_id,
            [ProposedChange("repeat\nrepeat\n", "ok"), ProposedChange("nope", "x")],
        )
    assert await store.suggestions.list_for_document(OWNER, doc_id) == []

    with pytest.raises(ValueError):
        await store.suggestions.propose(OWNER, doc_id, [])


# --- accept / reject ------------------------------------------------------


async def test_accepting_one_change_applies_it_and_mints_exactly_one_version():
    store, adapter = await _store()
    doc_id = await _doc(store)
    proposed = await store.suggestions.propose(
        OWNER,
        doc_id,
        [
            ProposedChange("Alpha line.", "Alpha line, revised."),
            ProposedChange("Gamma line.", "Gamma line, revised."),
        ],
    )
    adapter.indexed.clear()

    applied = await store.suggestions.accept(OWNER, proposed.changes[0].id)

    assert applied.version == 2 and applied.created_at is not None
    assert applied.accepted == (proposed.changes[0].id,) and applied.skipped == ()
    assert applied.document.body == "Alpha line, revised.\nBeta line.\nGamma line.\n"

    versions = await store.list_versions(OWNER, doc_id)
    assert [v.version for v in versions] == [2, 1]
    assert versions[0].origin == "ai"  # only accepting writes to the history
    assert adapter.indexed == [(doc_id, applied.document.body)]

    # The untouched sibling is still pending; the accepted one records its version.
    still = (await store.suggestions.list_for_document(OWNER, doc_id))[0]
    by_id = {c.id: c for c in still.changes}
    assert by_id[proposed.changes[0].id].status == "accepted"
    assert by_id[proposed.changes[0].id].version == 2
    assert by_id[proposed.changes[1].id].status == "pending"
    assert still.pending == 1


async def test_rejecting_a_change_mints_no_version_and_leaves_the_body_alone():
    store, adapter = await _store()
    doc_id = await _doc(store)
    proposed = await store.suggestions.propose(
        OWNER, doc_id, [ProposedChange("Beta line.", "Beta line, revised.")]
    )
    adapter.indexed.clear()

    rejected = await store.suggestions.reject(OWNER, proposed.changes[0].id)

    assert rejected.status == "rejected" and rejected.version is None
    assert rejected.decided_at is not None
    assert (await store.get(OWNER, doc_id)).body == BODY
    assert [v.version for v in await store.list_versions(OWNER, doc_id)] == [1]
    assert adapter.indexed == []

    # A decided change can't be decided twice.
    with pytest.raises(NotFoundError):
        await store.suggestions.accept(OWNER, proposed.changes[0].id)
    with pytest.raises(NotFoundError):
        await store.suggestions.reject(OWNER, proposed.changes[0].id)

    # A fully reviewed set drops out of the pending list but survives in history.
    assert await store.suggestions.list_for_document(OWNER, doc_id) == []
    assert len(await store.suggestions.list_for_document(OWNER, doc_id, include_resolved=True)) == 1


# --- accept-all -----------------------------------------------------------


async def test_accept_all_applies_every_pending_change_as_one_version():
    store, _ = await _store()
    doc_id = await _doc(store)
    proposed = await store.suggestions.propose(
        OWNER,
        doc_id,
        [
            # Deliberately out of document order, to prove the apply order is derived from
            # the body rather than from the order the AI produced them.
            ProposedChange("Gamma line.", "Gamma revised."),
            ProposedChange("Alpha line.", "Alpha revised."),
            ProposedChange("Beta line.", "Beta revised."),
        ],
    )

    applied = await store.suggestions.accept_all(OWNER, proposed.id)

    assert applied.document.body == "Alpha revised.\nBeta revised.\nGamma revised.\n"
    assert len(applied.accepted) == 3 and applied.skipped == ()
    # Three changes, one coherent result, one version.
    assert applied.version == 2
    assert [v.version for v in await store.list_versions(OWNER, doc_id)] == [2, 1]
    assert await store.suggestions.list_for_document(OWNER, doc_id) == []


async def test_accept_all_skips_a_change_already_decided_on_its_own():
    store, _ = await _store()
    doc_id = await _doc(store)
    proposed = await store.suggestions.propose(
        OWNER,
        doc_id,
        [
            ProposedChange("Alpha line.", "Alpha revised."),
            ProposedChange("Beta line.", "Beta revised."),
            ProposedChange("Gamma line.", "Gamma revised."),
        ],
    )
    await store.suggestions.reject(OWNER, proposed.changes[1].id)

    applied = await store.suggestions.accept_all(OWNER, proposed.id)

    # The rejected change is not resurrected by accept-all.
    assert applied.document.body == "Alpha revised.\nBeta line.\nGamma revised.\n"
    assert len(applied.accepted) == 2
    assert [v.version for v in await store.list_versions(OWNER, doc_id)] == [2, 1]


async def test_sequential_changes_on_adjacent_text_apply_cleanly():
    """Changes whose spans sit right next to each other — the case where an offset-based
    patch would drift after the first replacement rewrites the length of the text."""
    store, _ = await _store()
    doc_id = await _doc(store, "one two three four")
    proposed = await store.suggestions.propose(
        OWNER,
        doc_id,
        [
            ProposedChange("one ", "1111111111 "),
            ProposedChange("two ", "2 "),
            ProposedChange("three ", "3333 "),
            ProposedChange("four", "4"),
        ],
    )

    applied = await store.suggestions.accept_all(OWNER, proposed.id)

    assert applied.document.body == "1111111111 2 3333 4"
    assert len(applied.accepted) == 4 and applied.skipped == ()


async def test_overlapping_changes_apply_one_and_leave_the_other_pending():
    """Two proposals over the same stretch of text: the first in document order wins, the
    one whose anchor it destroyed is skipped and stays pending — never half-applied."""
    store, _ = await _store()
    doc_id = await _doc(store, "the quick brown fox")
    proposed = await store.suggestions.propose(
        OWNER,
        doc_id,
        [
            ProposedChange("quick brown", "slow grey"),
            ProposedChange("brown fox", "brown hound"),
        ],
    )

    applied = await store.suggestions.accept_all(OWNER, proposed.id)

    assert applied.document.body == "the slow grey fox"
    assert applied.accepted == (proposed.changes[0].id,)
    assert applied.skipped == ((proposed.changes[1].id, 0),)
    # One version for the one change that landed, and the loser is still reviewable.
    assert [v.version for v in await store.list_versions(OWNER, doc_id)] == [2, 1]
    remaining = (await store.suggestions.list_for_document(OWNER, doc_id))[0]
    assert remaining.pending == 1


# --- the document moved underneath the suggestion -------------------------


async def test_accepting_a_change_whose_span_has_since_changed_refuses():
    store, _ = await _store()
    doc_id = await _doc(store)
    proposed = await store.suggestions.propose(
        OWNER, doc_id, [ProposedChange("Beta line.", "Beta line, revised.")]
    )

    # The operator edits the very span the suggestion was anchored to.
    await store.edit(OWNER, doc_id, body="Alpha line.\nBeta rewritten by hand.\n")

    with pytest.raises(DocumentSpanError) as refused:
        await store.suggestions.accept(OWNER, proposed.changes[0].id)
    assert refused.value.occurrences == 0

    # Nothing was corrupted and nothing was minted beyond the operator's own edit.
    assert (await store.get(OWNER, doc_id)).body == "Alpha line.\nBeta rewritten by hand.\n"
    assert [v.version for v in await store.list_versions(OWNER, doc_id)] == [2, 1]
    # The change is still pending — refusing is not deciding.
    assert (await store.suggestions.list_for_document(OWNER, doc_id))[0].pending == 1


async def test_accept_all_with_every_anchor_gone_writes_nothing():
    store, adapter = await _store()
    doc_id = await _doc(store)
    proposed = await store.suggestions.propose(
        OWNER,
        doc_id,
        [
            ProposedChange("Alpha line.", "Alpha revised."),
            ProposedChange("Beta line.", "Beta revised."),
        ],
    )
    await store.edit(OWNER, doc_id, body="Something else entirely.")
    adapter.indexed.clear()

    applied = await store.suggestions.accept_all(OWNER, proposed.id)

    assert applied.accepted == () and applied.version is None
    assert applied.created_at is None
    assert {change_id for change_id, _ in applied.skipped} == {c.id for c in proposed.changes}
    assert applied.document.body == "Something else entirely."
    # No version, no re-index — a no-op accept must not write.
    assert [v.version for v in await store.list_versions(OWNER, doc_id)] == [2, 1]
    assert adapter.indexed == []


# --- ownership, cleanup, and the streaming preview ------------------------


async def test_suggestions_are_owner_scoped_and_die_with_their_document():
    store, _ = await _store()
    doc_id = await _doc(store)
    proposed = await store.suggestions.propose(
        OWNER, doc_id, [ProposedChange("Beta line.", "Beta revised.")]
    )

    with pytest.raises(NotFoundError):
        await store.suggestions.list_for_document("someone-else", doc_id)
    with pytest.raises(NotFoundError):
        await store.suggestions.accept("someone-else", proposed.changes[0].id)
    with pytest.raises(NotFoundError):
        await store.suggestions.accept_all("someone-else", proposed.id)

    await store.delete(OWNER, doc_id)
    with pytest.raises(NotFoundError):
        await store.suggestions.accept(OWNER, proposed.changes[0].id)


def test_stream_preview_yields_a_running_body_and_skips_dead_anchors():
    steps = list(
        stream_preview(
            BODY,
            [
                ("Alpha line.", "Alpha revised."),
                ("not in the body", "ignored"),
                ("Gamma line.", "Gamma revised."),
            ],
        )
    )
    assert steps == [
        "Alpha revised.\nBeta line.\nGamma line.\n",
        "Alpha revised.\nBeta line.\nGamma revised.\n",
    ]
