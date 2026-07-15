"""Documents surface — the editable library with version history (`DOC-1`/`DOC-2`).

Thin pass-throughs to :class:`~services.documents.DocumentStore`: list/get, create,
edit, archive/restore, the version history, restore-to-version, and delete. Content is
returned decrypted — the operator owns it. Out-shapes are camelCase to match the
frontend's ``documents`` seam contracts (the screen swaps mocks for these without
changing its types). Document *search* is not here — it flows through ``/corpus`` like
every other source.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.exceptions import NotFoundError
from models.document import DocumentVersionOrigin
from routes import deps
from routes.camel import CamelModel
from routes.deps import OPERATOR_ID
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


@router.delete("/{document_id}", status_code=204)
async def delete_document(document_id: str, request: Request) -> None:
    try:
        await deps.documents(request).delete(OPERATOR_ID, document_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="document not found") from None
