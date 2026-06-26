"""Gallery — a presentation lens over the image uploads, plus operator albums.

The gallery owns no image bytes. Every image it shows is a row the
:class:`~services.uploads.UploadStore` already holds (``mime`` ``image/*``) — chat
attachments and knowledge-base uploads are the same `Upload`, so "all images uploaded"
is exactly that filter. This service adds two things on top of that view:

- **Provenance buckets** (system albums), derived at read time, never stored: every image
  is *chat* (referenced by a message) or *imported* (uploaded directly), plus an *all*
  bucket. The membership comes from :meth:`ConversationStore.referenced_upload_ids`, which
  reads the clear ``attachment_ids`` column — no decryption.
- **Custom albums** the operator creates and curates (:mod:`models.gallery`): a sealed
  name and a many-to-many membership. An image may sit in several.

Like the other surfaces it raises only :mod:`core.exceptions` domain errors; the route
layer maps them to HTTP. Filenames and album names are sealed, so listing decrypts them
in Python — single-operator scale, the same posture documents and uploads take.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Engine, delete, func
from sqlmodel import Session, select

from core.db import in_session
from core.exceptions import NotFoundError
from core.vault import Vault
from models.gallery import GalleryAlbum, GalleryAlbumItem
from models.upload import Upload
from services.conversations import ConversationStore
from services.uploads import UploadStore

# System (provenance) album ids — derived at read time, never rows. "all" is the unfiltered
# view; the other two split images by whether a chat message still references them.
SYS_ALL = "all"
SYS_CHAT = "sys-chat"
SYS_IMPORTED = "sys-imported"
_SYSTEM_ALBUM_IDS = frozenset({SYS_ALL, SYS_CHAT, SYS_IMPORTED})


@dataclass(frozen=True)
class GalleryMediaView:
    """One image as the gallery grid renders it. ``album_ids`` carries the provenance
    bucket (``sys-chat``/``sys-imported``) followed by every custom album it belongs to —
    the "all" bucket is implicit, so it isn't listed here."""

    id: str
    title: str  # the upload's filename (decrypted)
    type: str  # always "image" in v1 (the surface filters to image/*)
    favorite: bool
    kb_excluded: bool
    size_bytes: int
    created_at: datetime
    album_ids: list[str]


@dataclass(frozen=True)
class GalleryAlbumView:
    """An album row for the sidebar — system buckets first, then the operator's own.
    ``system`` albums are non-editable (no rename/delete/membership writes)."""

    id: str
    name: str
    count: int
    system: bool


class GalleryService:
    def __init__(
        self,
        engine: Engine,
        vault: Vault,
        conversations: ConversationStore,
        uploads: UploadStore,
    ) -> None:
        self._engine = engine
        self._vault = vault
        self._conversations = conversations
        self._uploads = uploads

    # --- read path --------------------------------------------------------

    async def list_media(self, owner_id: str) -> list[GalleryMediaView]:
        """Every image upload, newest first, tagged with its provenance bucket + custom
        album membership. One pass over the owner's image rows + one membership query."""
        referenced = await self._conversations.referenced_upload_ids(owner_id)

        def work(session: Session) -> tuple[list[Upload], dict[str, list[str]]]:
            images = session.exec(
                select(Upload)
                .where(
                    Upload.owner_id == owner_id,
                    Upload.mime.startswith("image/"),  # type: ignore[attr-defined]
                )
                .order_by(Upload.created_at.desc())  # type: ignore[attr-defined]
            ).all()
            membership: dict[str, list[str]] = {}
            rows = session.exec(
                select(GalleryAlbumItem.upload_id, GalleryAlbumItem.album_id).where(
                    GalleryAlbumItem.owner_id == owner_id
                )
            ).all()
            for upload_id, album_id in rows:
                membership.setdefault(upload_id, []).append(album_id)
            return list(images), membership

        images, membership = await in_session(self._engine, work)
        media: list[GalleryMediaView] = []
        for up in images:
            bucket = SYS_CHAT if up.id in referenced else SYS_IMPORTED
            media.append(
                GalleryMediaView(
                    id=up.id,
                    title=self._vault.decrypt_str(up.filename_enc),
                    type="image",
                    favorite=up.favorite,
                    kb_excluded=up.kb_excluded,
                    size_bytes=up.size_bytes,
                    created_at=up.created_at,
                    album_ids=[bucket, *membership.get(up.id, [])],
                )
            )
        return media

    async def list_albums(self, owner_id: str) -> list[GalleryAlbumView]:
        """The album sidebar: system buckets (with derived counts) then the operator's own
        albums (with membership counts)."""
        referenced = await self._conversations.referenced_upload_ids(owner_id)

        def work(
            session: Session,
        ) -> tuple[set[str], list[GalleryAlbum], dict[str, int]]:
            image_ids = set(
                session.exec(
                    select(Upload.id).where(
                        Upload.owner_id == owner_id,
                        Upload.mime.startswith("image/"),  # type: ignore[attr-defined]
                    )
                ).all()
            )
            albums = session.exec(
                select(GalleryAlbum)
                .where(GalleryAlbum.owner_id == owner_id)
                .order_by(GalleryAlbum.created_at)  # type: ignore[attr-defined]
            ).all()
            counts = dict(
                session.exec(
                    select(GalleryAlbumItem.album_id, func.count())
                    .where(GalleryAlbumItem.owner_id == owner_id)
                    .group_by(GalleryAlbumItem.album_id)
                ).all()
            )
            return image_ids, list(albums), counts

        image_ids, albums, counts = await in_session(self._engine, work)
        total = len(image_ids)
        chat = len(image_ids & referenced)
        result = [
            GalleryAlbumView(SYS_ALL, "All", total, True),
            GalleryAlbumView(SYS_CHAT, "Chat attachments", chat, True),
            GalleryAlbumView(SYS_IMPORTED, "Imported", total - chat, True),
        ]
        result.extend(
            GalleryAlbumView(
                a.id, self._vault.decrypt_str(a.name_enc), counts.get(a.id, 0), False
            )
            for a in albums
        )
        return result

    # --- album CRUD -------------------------------------------------------

    async def create_album(self, owner_id: str, name: str) -> GalleryAlbumView:
        """Create an empty custom album. The name is sealed; the caller validates it is
        non-empty."""
        clean = name.strip()
        name_enc = self._vault.encrypt_str(clean)

        def work(session: Session) -> str:
            album = GalleryAlbum(owner_id=owner_id, name_enc=name_enc)
            session.add(album)
            session.flush()
            return album.id

        album_id = await in_session(self._engine, work)
        return GalleryAlbumView(album_id, clean, 0, False)

    async def rename_album(
        self, owner_id: str, album_id: str, name: str
    ) -> GalleryAlbumView:
        """Rename a custom album. A system bucket isn't a real album, so it 404s."""
        self._reject_system(album_id)
        clean = name.strip()
        name_enc = self._vault.encrypt_str(clean)

        def work(session: Session) -> int:
            album = self._require_album(session, owner_id, album_id)
            album.name_enc = name_enc
            album.updated_at = datetime.now(UTC)
            session.add(album)
            session.flush()
            return self._count_items(session, album_id)

        count = await in_session(self._engine, work)
        return GalleryAlbumView(album_id, clean, count, False)

    async def delete_album(self, owner_id: str, album_id: str) -> None:
        """Delete a custom album. Its memberships cascade away; the images are untouched."""
        self._reject_system(album_id)

        def work(session: Session) -> None:
            album = self._require_album(session, owner_id, album_id)
            session.delete(album)

        await in_session(self._engine, work)

    # --- membership -------------------------------------------------------

    async def add_item(self, owner_id: str, album_id: str, upload_id: str) -> None:
        """Add an image to a custom album. Validates the upload is the operator's image and
        the album is real; idempotent (re-adding an already-member image is a no-op)."""
        self._reject_system(album_id)
        if not await self._uploads.image_ids(owner_id, [upload_id]):
            raise NotFoundError(f"image {upload_id!r} not found")

        def work(session: Session) -> None:
            self._require_album(session, owner_id, album_id)
            already = session.exec(
                select(GalleryAlbumItem.id).where(
                    GalleryAlbumItem.album_id == album_id,
                    GalleryAlbumItem.upload_id == upload_id,
                )
            ).first()
            if already is None:
                session.add(
                    GalleryAlbumItem(
                        owner_id=owner_id, album_id=album_id, upload_id=upload_id
                    )
                )

        await in_session(self._engine, work)

    async def remove_item(self, owner_id: str, album_id: str, upload_id: str) -> None:
        """Remove an image from a custom album (no-op if it wasn't a member). 404s on a
        system bucket or an album that isn't the operator's — same guard its sibling mutators
        carry, so a stale/foreign album id is reported, not silently accepted."""
        self._reject_system(album_id)

        def work(session: Session) -> None:
            self._require_album(session, owner_id, album_id)
            session.execute(
                delete(GalleryAlbumItem).where(
                    GalleryAlbumItem.owner_id == owner_id,
                    GalleryAlbumItem.album_id == album_id,
                    GalleryAlbumItem.upload_id == upload_id,
                )
            )

        await in_session(self._engine, work)

    # --- curation guard (delete-choice safety) ----------------------------

    async def curated_image_ids(
        self, owner_id: str, upload_ids: list[str]
    ) -> set[str]:
        """Of ``upload_ids``, those the operator has deliberately curated — favorited or filed
        into a custom album — and so must not be swept away as "unused" when a conversation
        that happens to reference them is deleted. A clear-column read; decrypts nothing."""
        wanted = list(dict.fromkeys(upload_ids))
        if not wanted:
            return set()

        def work(session: Session) -> set[str]:
            favorited = set(
                session.exec(
                    select(Upload.id).where(
                        Upload.owner_id == owner_id,
                        Upload.id.in_(wanted),  # type: ignore[attr-defined]
                        Upload.favorite.is_(True),  # type: ignore[attr-defined]
                    )
                ).all()
            )
            in_album = set(
                session.exec(
                    select(GalleryAlbumItem.upload_id).where(
                        GalleryAlbumItem.owner_id == owner_id,
                        GalleryAlbumItem.upload_id.in_(wanted),  # type: ignore[attr-defined]
                    )
                ).all()
            )
            return favorited | in_album

        return await in_session(self._engine, work)

    # --- internals --------------------------------------------------------

    @staticmethod
    def _reject_system(album_id: str) -> None:
        if album_id in _SYSTEM_ALBUM_IDS:
            raise NotFoundError(f"album {album_id!r} is not an editable album")

    @staticmethod
    def _require_album(session: Session, owner_id: str, album_id: str) -> GalleryAlbum:
        album = session.get(GalleryAlbum, album_id)
        if album is None or album.owner_id != owner_id:
            raise NotFoundError(f"album {album_id!r} not found")
        return album

    @staticmethod
    def _count_items(session: Session, album_id: str) -> int:
        return session.exec(
            select(func.count())
            .select_from(GalleryAlbumItem)
            .where(GalleryAlbumItem.album_id == album_id)
        ).one()
