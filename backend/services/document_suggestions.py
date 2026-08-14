"""Document suggestions — propose a change, review it change-by-change, apply only what
the operator accepts (`DOC-3`).

The other half of the document assist story. ``DocumentStore`` handles the two ways the
agent changes a document *now* — a full rewrite and a targeted edit — and both mint a
version the moment they run. This module handles the third way: **proposing**. Nothing
here touches the document until the operator says so.

The whole design follows from one rule:

> **Only accepting mints a version.** Proposing writes suggestion rows and leaves the
> document byte-identical. Rejecting writes a status and leaves the document
> byte-identical. Accepting is the single path that reaches ``documents``/
> ``document_versions`` — so the version history stays what it has always been, a record
> of changes that actually happened, with no "proposed" limbo in it.

**Spans are anchored by text, never by offset.** Each change stores the exact stretch it
replaces, and applying it re-finds that stretch in whatever the document says *at accept
time* via the shared :func:`core.text.replace_unique`. That is what makes a suggestion
survive the document being edited underneath it: if the anchor is still there and still
unique it applies cleanly; if the document moved, the accept **refuses with the occurrence
count** rather than guessing which span was meant. Offsets could not do that — they would
silently point at the wrong text.

**Accepting several changes is one version, applied in document order.** ``accept_all``
walks the pending changes sorted by where their anchors sit in the current body, applies
each to the running text, and snapshots **once** at the end — the operator agreed to one
coherent result, so the history records one. Because each step re-anchors by text rather
than arithmetic on positions, earlier replacements cannot corrupt later ones; ordering by
position only makes the outcome deterministic, and makes an overlapping pair fail the
*later* change (which is then left pending, never half-applied).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Engine
from sqlmodel import Session, select

from core.db import in_session
from core.exceptions import DocumentSpanError, NotFoundError
from core.text import replace_unique
from core.vault import Vault
from models.document import Document, DocumentVersion, DocumentVersionOrigin
from models.document_suggestion import (
    DocumentSuggestionChange,
    DocumentSuggestionSet,
    SuggestionStatus,
)
from services.corpus.documents import DocumentsAdapter
from services.documents import DocumentView, document_view, snapshot_version, write_body


@dataclass(frozen=True)
class ProposedChange:
    """One change on the way *in* — an anchored span plus why it's being proposed."""

    old_text: str
    new_text: str
    explanation: str = ""


@dataclass(frozen=True)
class SuggestionChangeView:
    """One decrypted proposed change, as the review UI renders it."""

    id: str
    set_id: str
    ordinal: int
    old_text: str
    new_text: str
    explanation: str
    status: str
    # The version this change minted when accepted (null while pending, and forever if
    # rejected — a rejected change never reaches the history).
    version: int | None
    created_at: datetime
    decided_at: datetime | None


@dataclass(frozen=True)
class SuggestionSetView:
    """One AI pass over a document: its summary and its individual changes, oldest first."""

    id: str
    document_id: str
    conversation_id: str | None
    summary: str
    created_at: datetime
    changes: tuple[SuggestionChangeView, ...]

    @property
    def pending(self) -> int:
        """How many changes still await a decision — what makes a set worth showing."""
        return sum(1 for c in self.changes if c.status == SuggestionStatus.PENDING)


@dataclass(frozen=True)
class SuggestionApplied:
    """The outcome of accepting — one change or a whole set.

    ``version`` is the single version the accepted changes minted, or ``None`` when
    nothing applied (every candidate's anchor had moved), in which case the document was
    not written at all. ``skipped`` carries ``(change_id, occurrences)`` for each change
    left pending because its anchor no longer matched exactly one span."""

    document: DocumentView
    version: int | None
    created_at: datetime | None
    accepted: tuple[str, ...]
    skipped: tuple[tuple[str, int], ...]


def stream_preview(body: str, changes: Iterable[tuple[str, str]]) -> Iterator[str]:
    """Yield the running "what the document would say" body after each change lands.

    Pure text — it writes nothing. It exists so the tool layer can stream a proposal into
    the View *as it is produced* without re-implementing the anchoring rule: a change whose
    anchor doesn't resolve is skipped and the preview simply doesn't move, exactly as
    accepting it later would refuse."""
    preview = body
    for old_text, new_text in changes:
        try:
            preview = replace_unique(preview, old_text, new_text, error=DocumentSpanError)
        except DocumentSpanError:
            continue
        yield preview


class DocumentSuggestionStore:
    """The suggestion lifecycle. Constructed by (and reached through)
    :class:`~services.documents.DocumentStore` as ``store.suggestions``, sharing its
    engine, vault, and corpus adapter so an accepted change re-indexes like any other
    write."""

    def __init__(self, engine: Engine, vault: Vault, adapter: DocumentsAdapter) -> None:
        self._engine = engine
        self._vault = vault
        self._adapter = adapter

    # --- propose ----------------------------------------------------------

    async def propose(
        self,
        owner_id: str,
        document_id: str,
        changes: Sequence[ProposedChange],
        *,
        summary: str = "",
        conversation_id: str | None = None,
    ) -> SuggestionSetView:
        """Record one AI pass as a pending suggestion set. **The document is not touched.**

        Every anchor is checked against the current body up front and the whole set is
        refused (:class:`DocumentSpanError`, carrying the count) if any one of them is
        absent or ambiguous — so the proposer finds out immediately, rather than the
        operator discovering a dud change at review time. The check runs inside the write
        transaction, so it reflects the body the set is actually proposed against."""
        if not changes:
            raise ValueError("a suggestion set needs at least one change")

        def work(session: Session) -> SuggestionSetView:
            document = _require(session, owner_id, document_id)
            body = self._vault.decrypt_str(document.body_enc)
            for change in changes:
                occurrences = body.count(change.old_text) if change.old_text else 0
                if occurrences != 1:
                    raise DocumentSpanError(occurrences)
            suggestion_set = DocumentSuggestionSet(
                owner_id=owner_id,
                document_id=document_id,
                conversation_id=conversation_id,
                summary_enc=self._vault.encrypt_str(summary),
            )
            session.add(suggestion_set)
            session.flush()
            rows = [
                DocumentSuggestionChange(
                    owner_id=owner_id,
                    set_id=suggestion_set.id,
                    document_id=document_id,
                    ordinal=ordinal,
                    old_text_enc=self._vault.encrypt_str(change.old_text),
                    new_text_enc=self._vault.encrypt_str(change.new_text),
                    explanation_enc=self._vault.encrypt_str(change.explanation),
                )
                for ordinal, change in enumerate(changes)
            ]
            for row in rows:
                session.add(row)
            session.flush()
            return self._set_view(suggestion_set, rows)

        return await in_session(self._engine, work)

    # --- review -----------------------------------------------------------

    async def list_for_document(
        self, owner_id: str, document_id: str, *, include_resolved: bool = False
    ) -> list[SuggestionSetView]:
        """A document's suggestion sets, newest first. Pending-only by default — a fully
        reviewed set is history, not a decision the operator still owes."""

        def work(session: Session) -> list[SuggestionSetView]:
            _require(session, owner_id, document_id)
            sets = session.exec(
                select(DocumentSuggestionSet)
                .where(
                    DocumentSuggestionSet.owner_id == owner_id,
                    DocumentSuggestionSet.document_id == document_id,
                )
                .order_by(DocumentSuggestionSet.created_at.desc())  # type: ignore[attr-defined]
            ).all()
            if not sets:
                return []
            changes = session.exec(
                select(DocumentSuggestionChange)
                .where(DocumentSuggestionChange.set_id.in_([s.id for s in sets]))  # type: ignore[attr-defined]
                .order_by(DocumentSuggestionChange.ordinal)  # type: ignore[attr-defined]
            ).all()
            by_set: dict[str, list[DocumentSuggestionChange]] = {}
            for change in changes:
                by_set.setdefault(change.set_id, []).append(change)
            views = [self._set_view(s, by_set.get(s.id, [])) for s in sets]
            return [v for v in views if include_resolved or v.pending]

        return await in_session(self._engine, work)

    async def reject(
        self, owner_id: str, change_id: str, *, document_id: str | None = None
    ) -> SuggestionChangeView:
        """Decline one change. Writes a status and nothing else — no version, no edit to
        the document, no trace in the history. ``document_id`` is an optional scope guard
        for callers that reached the change through a document (a nested REST path), so a
        mismatched pair is a not-found rather than a decision on some other document."""

        def work(session: Session) -> SuggestionChangeView:
            change = _require_pending(session, owner_id, change_id, document_id)
            change.status = SuggestionStatus.REJECTED
            change.decided_at = datetime.now(UTC)
            session.add(change)
            session.flush()
            return self._change_view(change)

        return await in_session(self._engine, work)

    # --- accept -----------------------------------------------------------

    async def accept(
        self, owner_id: str, change_id: str, *, document_id: str | None = None
    ) -> SuggestionApplied:
        """Apply exactly one proposed change and mint **one** version (origin ``ai``).

        Raises :class:`DocumentSpanError` — leaving the change pending and the document
        untouched — when the anchor no longer matches exactly one span, so a document that
        moved underneath a suggestion refuses rather than corrupting. ``document_id`` is
        the same optional scope guard :meth:`reject` takes."""

        def work(session: Session) -> tuple[SuggestionApplied, str]:
            change = _require_pending(session, owner_id, change_id, document_id)
            document = _require(session, owner_id, change.document_id)
            body = self._vault.decrypt_str(document.body_enc)
            new_body = replace_unique(
                body,
                self._vault.decrypt_str(change.old_text_enc),
                self._vault.decrypt_str(change.new_text_enc),
                error=DocumentSpanError,
            )
            snapshot = self._commit_body(session, document, new_body)
            _mark_accepted(session, change, snapshot.version)
            title = self._vault.decrypt_str(document.title_enc)
            applied = SuggestionApplied(
                document=document_view(document, title, new_body),
                version=snapshot.version,
                created_at=snapshot.created_at,
                accepted=(change.id,),
                skipped=(),
            )
            return applied, new_body

        applied, new_body = await in_session(self._engine, work)
        self._adapter.index_document(owner_id, applied.document.id, new_body)
        return applied

    async def accept_all(
        self, owner_id: str, set_id: str, *, document_id: str | None = None
    ) -> SuggestionApplied:
        """Apply every still-pending change in a set as **one** version.

        Changes are applied in the order their anchors appear in the current body, each
        re-anchored against the running text — see the module docstring for why that is the
        stable order. A change whose anchor has moved is **skipped and left pending** rather
        than failing the batch, so one stale change can't block the rest; the skipped ids
        come back in the result. If nothing applies, no version is minted and the document
        is not written."""

        def work(session: Session) -> tuple[SuggestionApplied, str | None]:
            suggestion_set = session.get(DocumentSuggestionSet, set_id)
            if (
                suggestion_set is None
                or suggestion_set.owner_id != owner_id
                or (document_id is not None and suggestion_set.document_id != document_id)
            ):
                raise NotFoundError(f"suggestion set {set_id!r} not found")
            document = _require(session, owner_id, suggestion_set.document_id)
            body = self._vault.decrypt_str(document.body_enc)
            pending = session.exec(
                select(DocumentSuggestionChange)
                .where(
                    DocumentSuggestionChange.set_id == set_id,
                    DocumentSuggestionChange.status == SuggestionStatus.PENDING,
                )
                .order_by(DocumentSuggestionChange.ordinal)  # type: ignore[attr-defined]
            ).all()
            spans = [
                (
                    row,
                    self._vault.decrypt_str(row.old_text_enc),
                    self._vault.decrypt_str(row.new_text_enc),
                )
                for row in pending
            ]
            # Document order (anchors absent from the body sort last, then by ordinal) —
            # deterministic, and it decides *which* of an overlapping pair wins rather than
            # leaving it to insertion order.
            spans.sort(key=lambda s: (_position(body, s[1]), s[0].ordinal))

            working = body
            accepted: list[DocumentSuggestionChange] = []
            skipped: list[tuple[str, int]] = []
            for row, old_text, new_text in spans:
                try:
                    working = replace_unique(
                        working, old_text, new_text, error=DocumentSpanError
                    )
                except DocumentSpanError as exc:
                    skipped.append((row.id, exc.occurrences))
                    continue
                accepted.append(row)

            title = self._vault.decrypt_str(document.title_enc)
            if not accepted:
                nothing = SuggestionApplied(
                    document=document_view(document, title, body),
                    version=None,
                    created_at=None,
                    accepted=(),
                    skipped=tuple(skipped),
                )
                return nothing, None

            snapshot = self._commit_body(session, document, working)
            for row in accepted:
                _mark_accepted(session, row, snapshot.version)
            applied = SuggestionApplied(
                document=document_view(document, title, working),
                version=snapshot.version,
                created_at=snapshot.created_at,
                accepted=tuple(row.id for row in accepted),
                skipped=tuple(skipped),
            )
            return applied, working

        applied, new_body = await in_session(self._engine, work)
        if new_body is not None:
            self._adapter.index_document(owner_id, applied.document.id, new_body)
        return applied

    # --- internals --------------------------------------------------------

    def purge_document(self, session: Session, document_id: str) -> None:
        """Drop a document's suggestion rows inside the caller's transaction — used by the
        hard-delete path so nothing about a deleted document outlives it."""
        for change in session.exec(
            select(DocumentSuggestionChange).where(
                DocumentSuggestionChange.document_id == document_id
            )
        ).all():
            session.delete(change)
        for suggestion_set in session.exec(
            select(DocumentSuggestionSet).where(
                DocumentSuggestionSet.document_id == document_id
            )
        ).all():
            session.delete(suggestion_set)

    def _commit_body(
        self, session: Session, document: Document, body: str
    ) -> DocumentVersion:
        """Seal a new body onto the document and snapshot it as one ``ai``-origin version —
        the single write an accept performs, shared by ``accept`` and ``accept_all``."""
        write_body(self._vault, document, body)
        document.updated_at = datetime.now(UTC)
        session.add(document)
        session.flush()
        return snapshot_version(session, document, DocumentVersionOrigin.AI)

    def _set_view(
        self, row: DocumentSuggestionSet, changes: Sequence[DocumentSuggestionChange]
    ) -> SuggestionSetView:
        return SuggestionSetView(
            id=row.id,
            document_id=row.document_id,
            conversation_id=row.conversation_id,
            summary=self._vault.decrypt_str(row.summary_enc),
            created_at=row.created_at,
            changes=tuple(
                self._change_view(c) for c in sorted(changes, key=lambda c: c.ordinal)
            ),
        )

    def _change_view(self, row: DocumentSuggestionChange) -> SuggestionChangeView:
        return SuggestionChangeView(
            id=row.id,
            set_id=row.set_id,
            ordinal=row.ordinal,
            old_text=self._vault.decrypt_str(row.old_text_enc),
            new_text=self._vault.decrypt_str(row.new_text_enc),
            explanation=self._vault.decrypt_str(row.explanation_enc),
            status=row.status,
            version=row.version,
            created_at=row.created_at,
            decided_at=row.decided_at,
        )


def _require(session: Session, owner_id: str, document_id: str) -> Document:
    document = session.get(Document, document_id)
    if document is None or document.owner_id != owner_id:
        raise NotFoundError(f"document {document_id!r} not found")
    return document


def _require_pending(
    session: Session, owner_id: str, change_id: str, document_id: str | None = None
) -> DocumentSuggestionChange:
    """The one pending change with this id, or a not-found. An already-decided change is
    *not* found on purpose: accepting or rejecting twice must never be a second decision."""
    change = session.get(DocumentSuggestionChange, change_id)
    if (
        change is None
        or change.owner_id != owner_id
        or change.status != SuggestionStatus.PENDING
        or (document_id is not None and change.document_id != document_id)
    ):
        raise NotFoundError(f"pending suggestion {change_id!r} not found")
    return change


def _mark_accepted(
    session: Session, change: DocumentSuggestionChange, version: int
) -> None:
    change.status = SuggestionStatus.ACCEPTED
    change.version = version
    change.decided_at = datetime.now(UTC)
    session.add(change)


def _position(body: str, old_text: str) -> int:
    """Where a change's anchor sits in the body — absent anchors sort last."""
    index = body.find(old_text)
    return index if index >= 0 else len(body) + 1
