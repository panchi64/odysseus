"""Gallery schema — operator-curated albums over the image uploads.

The gallery itself is **not** a store: it is a presentation lens over the rows the
:class:`~models.upload.Upload` table already holds (every ``image/*`` upload — chat
attachments and knowledge-base uploads alike). What *is* durable here is the operator's
own organization of those images: named **albums** and the **membership** linking an
image into them. System albums ("all", chat-attachments, imported) are derived from
provenance at read time and own no rows; only the operator's custom albums live here.

At-rest posture mirrors documents and memory: an album's ``name`` is the operator's own
content, so it is **encrypted at rest** under the vault. Structural metadata — the
``owner_id`` seam, the two foreign keys, timestamps — stays in the clear so the DB can
list and join without unsealing.

Membership is a many-to-many link (an image may sit in several albums). Both foreign
keys cascade on delete, so deleting an album drops its memberships and deleting the
underlying upload (from the gallery or anywhere else) drops the rows that pointed at it
— no orphan link survives a delete on either side. SQLite enforces this because
``core.db`` turns ``PRAGMA foreign_keys=ON`` on for every connection.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, ForeignKey, String, UniqueConstraint
from sqlmodel import Field, SQLModel

from models._fields import new_id, utcnow


class GalleryAlbum(SQLModel, table=True):
    __tablename__ = "gallery_albums"

    id: str = Field(default_factory=new_id, primary_key=True)
    owner_id: str = Field(index=True)
    # AEAD ciphertext of the album name (operator content) — sealed like a document title.
    name_enc: str
    created_at: datetime = Field(default_factory=utcnow, index=True)
    updated_at: datetime = Field(default_factory=utcnow)


class GalleryAlbumItem(SQLModel, table=True):
    __tablename__ = "gallery_album_items"
    # One image sits in an album at most once — a re-add is idempotent, not a duplicate.
    __table_args__ = (
        UniqueConstraint("album_id", "upload_id", name="uq_gallery_album_item"),
    )

    id: str = Field(default_factory=new_id, primary_key=True)
    owner_id: str = Field(index=True)
    # Both sides cascade: dropping the album removes its memberships; deleting the upload
    # (gallery delete, or a chat-attachment purge) removes the rows that referenced it.
    album_id: str = Field(
        sa_column=Column(
            String,
            ForeignKey("gallery_albums.id", ondelete="CASCADE"),
            index=True,
            nullable=False,
        )
    )
    upload_id: str = Field(
        sa_column=Column(
            String,
            ForeignKey("uploads.id", ondelete="CASCADE"),
            index=True,
            nullable=False,
        )
    )
    created_at: datetime = Field(default_factory=utcnow)
