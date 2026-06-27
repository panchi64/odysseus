"""Workspace history — content-addressed snapshots of the agent's sandbox.

After a turn that changed files, the workspace's text files are captured as a
**snapshot**: a point-in-time tree the operator can browse (code) and diff against
the previous one. File bytes are content-addressed and **encrypted at rest** under
the vault, deduped across snapshots by content hash; the snapshot's manifest
(path → hash) and small change-stats stay in the clear (like an artifact's
filename) — the file *content* does not.

Keyed by ``conversation_id`` — not a foreign key, because a snapshot can also come
from a stateless run (keyed by its run id). Every record carries the ``owner_id``
seam.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from models._fields import new_id, utcnow


class WorkspaceBlob(SQLModel, table=True):
    __tablename__ = "workspace_blobs"
    # One row per distinct file content per owner — snapshots share blobs by hash.
    __table_args__ = (UniqueConstraint("owner_id", "sha256", name="uq_workspace_blob_owner_sha"),)

    id: str = Field(default_factory=new_id, primary_key=True)
    owner_id: str = Field(index=True)
    # Hex sha256 of the plaintext file bytes — the dedup key within an owner.
    sha256: str = Field(index=True)
    size: int
    # AEAD ciphertext of the file bytes (the source of truth).
    blob_enc: bytes
    created_at: datetime = Field(default_factory=utcnow)


class WorkspaceSnapshot(SQLModel, table=True):
    __tablename__ = "workspace_snapshots"

    id: str = Field(default_factory=new_id, primary_key=True)
    owner_id: str = Field(index=True)
    conversation_id: str = Field(index=True)
    run_id: str | None = None
    title: str | None = None
    # JSON {relpath: sha256}: the tree at this point. Structural metadata kept in
    # the clear (like Artifact.filename); the bytes it points at are encrypted.
    manifest_json: str
    # JSON {"added": n, "modified": n, "removed": n} vs. the previous snapshot.
    stats_json: str
    created_at: datetime = Field(default_factory=utcnow, index=True)
