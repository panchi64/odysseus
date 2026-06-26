"""Gallery surface — browse image media and curate albums.

Thin pass-throughs to :class:`~services.gallery.GalleryService`. The gallery is a lens
over the image uploads, so it owns no write path for the images themselves: favoriting,
deleting, importing, and toggling knowledge-base membership all flow through the existing
``/uploads`` endpoints (``PATCH``/``DELETE``/``POST``), and the bytes are served by
``/uploads/{id}/content`` and ``/uploads/{id}/thumbnail``. What lives here is the read
view (media + albums) and the album curation the operator does on top. Out-shapes are
camelCase to match the frontend ``gallery`` seam.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Request

from core.exceptions import NotFoundError
from routes import deps
from routes.camel import CamelModel
from routes.deps import OPERATOR_ID
from services.gallery import GalleryAlbumView, GalleryMediaView

router = APIRouter(prefix="/gallery", tags=["gallery"])


class MediaOut(CamelModel):
    id: str
    title: str
    type: str
    # Manual tagging is deferred (GAL-2); always empty in v1, kept so the seam is stable.
    tags: list[str] = []
    favorite: bool
    kb_excluded: bool
    album_ids: list[str]
    size_bytes: int
    created_at: datetime


class AlbumOut(CamelModel):
    id: str
    name: str
    count: int
    # System buckets (all / chat / imported) are non-editable; custom albums are not.
    system: bool


class AlbumBody(CamelModel):
    """Create or rename payload — the album's display name."""

    name: str


class AlbumItemIn(CamelModel):
    """Add-to-album payload — the image upload to enroll."""

    upload_id: str


def _media_out(view: GalleryMediaView) -> MediaOut:
    return MediaOut(
        id=view.id,
        title=view.title,
        type=view.type,
        favorite=view.favorite,
        kb_excluded=view.kb_excluded,
        album_ids=view.album_ids,
        size_bytes=view.size_bytes,
        created_at=view.created_at,
    )


def _album_out(view: GalleryAlbumView) -> AlbumOut:
    return AlbumOut(id=view.id, name=view.name, count=view.count, system=view.system)


def _require_name(body: AlbumBody) -> str:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="album name is required")
    return name


@router.get("/media", response_model=list[MediaOut])
async def list_media(request: Request) -> list[MediaOut]:
    views = await deps.gallery(request).list_media(OPERATOR_ID)
    return [_media_out(v) for v in views]


@router.get("/albums", response_model=list[AlbumOut])
async def list_albums(request: Request) -> list[AlbumOut]:
    views = await deps.gallery(request).list_albums(OPERATOR_ID)
    return [_album_out(v) for v in views]


@router.post("/albums", response_model=AlbumOut, status_code=201)
async def create_album(body: AlbumBody, request: Request) -> AlbumOut:
    view = await deps.gallery(request).create_album(OPERATOR_ID, _require_name(body))
    return _album_out(view)


@router.patch("/albums/{album_id}", response_model=AlbumOut)
async def rename_album(album_id: str, body: AlbumBody, request: Request) -> AlbumOut:
    try:
        view = await deps.gallery(request).rename_album(
            OPERATOR_ID, album_id, _require_name(body)
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="album not found") from None
    return _album_out(view)


@router.delete("/albums/{album_id}", status_code=204)
async def delete_album(album_id: str, request: Request) -> None:
    try:
        await deps.gallery(request).delete_album(OPERATOR_ID, album_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="album not found") from None


@router.post("/albums/{album_id}/items", status_code=204)
async def add_album_item(
    album_id: str, body: AlbumItemIn, request: Request
) -> None:
    try:
        await deps.gallery(request).add_item(OPERATOR_ID, album_id, body.upload_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@router.delete("/albums/{album_id}/items/{upload_id}", status_code=204)
async def remove_album_item(album_id: str, upload_id: str, request: Request) -> None:
    try:
        await deps.gallery(request).remove_item(OPERATOR_ID, album_id, upload_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="album not found") from None
