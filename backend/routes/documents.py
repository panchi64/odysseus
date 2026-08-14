"""Documents surface — the editable library with version history and AI suggestions
(`DOC-1`/`DOC-2`/`DOC-3`).

Thin pass-throughs to :class:`~services.documents.DocumentStore`: list/get, create,
edit, archive/restore, the version history, restore-to-version, delete, and the
**suggestion review** — list what the AI has proposed, then accept or reject it change by
change (or accept a whole set at once). Content is returned decrypted — the operator owns
it. Out-shapes are camelCase to match the frontend's ``documents`` seam contracts (the
screen swaps mocks for these without changing its types). Document *search* is not here —
it flows through ``/corpus`` like every other source.

The review routes are where `DOC-3`'s "before anything is applied" lives: accepting is the
only one of the three that writes to the document, and its response carries the version it
minted so the client labels it from backend truth rather than guessing.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.exceptions import DocumentSpanError, NotFoundError
from models.document import DocumentVersionOrigin
from routes import deps
from routes.camel import CamelModel
from routes.deps import OPERATOR_ID
from services.document_suggestions import (
    SuggestionApplied,
    SuggestionChangeView,
    SuggestionSetView,
)
from services.documents import DocumentSummaryView, DocumentVersionView, DocumentView

router = APIRouter(prefix="/documents", tags=["documents"])


class DocumentCreate(BaseModel):
    title: str
    body: str = ""


class DocumentUpdate(BaseModel):
    title: str | None = None
    body: str | None = None


class DocumentSummaryOut(CamelModel):
    """A library-list row — no body, just what the list renders (`DOC-1`)."""

    id: str
    title: str
    snippet: str
    word_count: int
    archived: bool
    created_at: datetime
    updated_at: datetime


class DocumentOut(CamelModel):
    id: str
    title: str
    body: str
    doc_type: str
    language: str | None = None
    archived: bool
    created_at: datetime
    updated_at: datetime
    # The document's current (highest) version number after this write. Set on the edit
    # response so the client can label the version it just minted without guessing; null on
    # reads that don't resolve it.
    version: int | None = None


class DocumentVersionOut(CamelModel):
    id: str
    version: int
    origin: str
    title: str
    body: str
    created_at: datetime
    # The operator's durable bookmark on this version.
    keeper: bool = False


class KeeperUpdate(BaseModel):
    keeper: bool


class SuggestionChangeOut(CamelModel):
    """One proposed change awaiting (or carrying) the operator's decision (`DOC-3`)."""

    id: str
    set_id: str
    ordinal: int
    old_text: str
    new_text: str
    explanation: str
    status: str
    # The version this change minted when accepted — null while pending, and null forever
    # if rejected (a rejected change never reaches the history).
    version: int | None = None
    created_at: datetime
    decided_at: datetime | None = None


class SuggestionSetOut(CamelModel):
    """One AI pass over a document, with its changes in the order they were produced."""

    id: str
    document_id: str
    conversation_id: str | None = None
    summary: str
    created_at: datetime
    changes: list[SuggestionChangeOut]
    # How many changes still await a decision — what the review UI badges.
    pending: int


class SuggestionAppliedOut(CamelModel):
    """The result of accepting. ``document`` is the document as it now stands and
    ``version`` the single version the accepted changes minted — null when nothing applied
    because every anchor had moved, in which case the document was not written at all.
    ``skipped`` names the changes left pending for that reason, so the client can say which
    ones need a fresh look rather than silently dropping them."""

    document: DocumentOut
    version: int | None = None
    accepted: list[str]
    skipped: list[str]


def _out(view: DocumentView, *, version: int | None = None) -> DocumentOut:
    return DocumentOut(
        id=view.id,
        title=view.title,
        body=view.body,
        doc_type=view.doc_type,
        language=view.language,
        archived=view.archived,
        created_at=view.created_at,
        updated_at=view.updated_at,
        version=version,
    )


def _summary_out(view: DocumentSummaryView) -> DocumentSummaryOut:
    return DocumentSummaryOut(
        id=view.id,
        title=view.title,
        snippet=view.snippet,
        word_count=view.word_count,
        archived=view.archived,
        created_at=view.created_at,
        updated_at=view.updated_at,
    )


def _change_out(view: SuggestionChangeView) -> SuggestionChangeOut:
    return SuggestionChangeOut(
        id=view.id,
        set_id=view.set_id,
        ordinal=view.ordinal,
        old_text=view.old_text,
        new_text=view.new_text,
        explanation=view.explanation,
        status=view.status,
        version=view.version,
        created_at=view.created_at,
        decided_at=view.decided_at,
    )


def _set_out(view: SuggestionSetView) -> SuggestionSetOut:
    return SuggestionSetOut(
        id=view.id,
        document_id=view.document_id,
        conversation_id=view.conversation_id,
        summary=view.summary,
        created_at=view.created_at,
        changes=[_change_out(c) for c in view.changes],
        pending=view.pending,
    )


def _applied_out(applied: SuggestionApplied) -> SuggestionAppliedOut:
    return SuggestionAppliedOut(
        document=_out(applied.document, version=applied.version),
        version=applied.version,
        accepted=list(applied.accepted),
        skipped=[change_id for change_id, _ in applied.skipped],
    )


def _version_out(view: DocumentVersionView) -> DocumentVersionOut:
    return DocumentVersionOut(
        id=view.id,
        version=view.version,
        origin=view.origin,
        title=view.title,
        body=view.body,
        created_at=view.created_at,
        keeper=view.keeper,
    )


@router.get("", response_model=list[DocumentSummaryOut])
async def list_documents(
    request: Request, include_archived: bool = False
) -> list[DocumentSummaryOut]:
    views = await deps.documents(request).list_documents(
        OPERATOR_ID, include_archived=include_archived
    )
    return [_summary_out(v) for v in views]


@router.post("", status_code=201, response_model=DocumentOut)
async def create_document(body: DocumentCreate, request: Request) -> DocumentOut:
    if not body.title.strip():
        raise HTTPException(status_code=422, detail="title must not be empty")
    view = await deps.documents(request).create(OPERATOR_ID, body.title, body.body)
    return _out(view)


@router.get("/{document_id}", response_model=DocumentOut)
async def get_document(document_id: str, request: Request) -> DocumentOut:
    try:
        view = await deps.documents(request).get(OPERATOR_ID, document_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="document not found") from None
    return _out(view)


@router.patch("/{document_id}", response_model=DocumentOut)
async def update_document(
    document_id: str, body: DocumentUpdate, request: Request
) -> DocumentOut:
    if body.title is not None and not body.title.strip():
        raise HTTPException(status_code=422, detail="title must not be empty")
    try:
        view, version = await deps.documents(request).edit(
            OPERATOR_ID,
            document_id,
            title=body.title,
            body=body.body,
            origin=DocumentVersionOrigin.USER,
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="document not found") from None
    # Report the version this edit minted so the client labels it from backend truth rather
    # than guessing — returned directly by the store, atomic with the write itself.
    return _out(view, version=version)


@router.post("/{document_id}/archive", response_model=DocumentOut)
async def archive_document(document_id: str, request: Request) -> DocumentOut:
    try:
        view = await deps.documents(request).archive(OPERATOR_ID, document_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="document not found") from None
    return _out(view)


@router.post("/{document_id}/restore", response_model=DocumentOut)
async def restore_document(document_id: str, request: Request) -> DocumentOut:
    try:
        view = await deps.documents(request).restore(OPERATOR_ID, document_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="document not found") from None
    return _out(view)


@router.get("/{document_id}/versions", response_model=list[DocumentVersionOut])
async def list_versions(document_id: str, request: Request) -> list[DocumentVersionOut]:
    try:
        views = await deps.documents(request).list_versions(OPERATOR_ID, document_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="document not found") from None
    return [_version_out(v) for v in views]


@router.post("/{document_id}/versions/{version}/restore", response_model=DocumentOut)
async def restore_version(document_id: str, version: int, request: Request) -> DocumentOut:
    try:
        view = await deps.documents(request).restore_version(OPERATOR_ID, document_id, version)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="document or version not found") from None
    return _out(view)


@router.post("/{document_id}/versions/{version}/keeper", status_code=204)
async def set_version_keeper(
    document_id: str, version: int, body: KeeperUpdate, request: Request
) -> None:
    """Bookmark or unbookmark a version — a durable keeper in the append-only history."""
    if not await deps.documents(request).set_keeper(
        OPERATOR_ID, document_id, version, body.keeper
    ):
        raise HTTPException(status_code=404, detail="document or version not found")


# --- suggestion review (`DOC-3`) -----------------------------------------------
# Change ids live under their own path segment rather than sharing `/suggestions/{id}`
# with set ids, so a route can never be ambiguous about which one it was handed.


@router.get("/{document_id}/suggestions", response_model=list[SuggestionSetOut])
async def list_suggestions(
    document_id: str, request: Request, include_resolved: bool = False
) -> list[SuggestionSetOut]:
    """What the AI has proposed for this document, newest set first. Pending-only by
    default — a fully reviewed set is history, not an outstanding decision."""
    try:
        views = await deps.documents(request).suggestions.list_for_document(
            OPERATOR_ID, document_id, include_resolved=include_resolved
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="document not found") from None
    return [_set_out(v) for v in views]


@router.post(
    "/{document_id}/suggestion-changes/{change_id}/accept",
    response_model=SuggestionAppliedOut,
)
async def accept_suggestion(
    document_id: str, change_id: str, request: Request
) -> SuggestionAppliedOut:
    """Apply one proposed change and mint the version it earns. 409 when the document has
    moved underneath the suggestion — the anchor no longer identifies one span, so the
    change stays pending and the document is left exactly as it was."""
    try:
        applied = await deps.documents(request).suggestions.accept(
            OPERATOR_ID, change_id, document_id=document_id
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="pending suggestion not found") from None
    except DocumentSpanError as exc:
        detail = (
            "the text this change applies to is no longer in the document"
            if exc.occurrences == 0
            else f"the text this change applies to now appears {exc.occurrences} times"
        )
        raise HTTPException(status_code=409, detail=detail) from None
    return _applied_out(applied)


@router.post("/{document_id}/suggestion-changes/{change_id}/reject", status_code=204)
async def reject_suggestion(document_id: str, change_id: str, request: Request) -> None:
    """Decline one proposed change. Writes a decision and nothing else — no version, no
    edit, no trace in the document's history."""
    try:
        await deps.documents(request).suggestions.reject(
            OPERATOR_ID, change_id, document_id=document_id
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="pending suggestion not found") from None


@router.post(
    "/{document_id}/suggestions/{set_id}/accept-all", response_model=SuggestionAppliedOut
)
async def accept_all_suggestions(
    document_id: str, set_id: str, request: Request
) -> SuggestionAppliedOut:
    """Apply every still-pending change in a set as one version. A change whose anchor has
    moved is reported in ``skipped`` and left pending rather than failing the batch, so one
    stale proposal can't block the rest."""
    try:
        applied = await deps.documents(request).suggestions.accept_all(
            OPERATOR_ID, set_id, document_id=document_id
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="suggestion set not found") from None
    return _applied_out(applied)


@router.delete("/{document_id}", status_code=204)
async def delete_document(document_id: str, request: Request) -> None:
    try:
        await deps.documents(request).delete(OPERATOR_ID, document_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="document not found") from None
