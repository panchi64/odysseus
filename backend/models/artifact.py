"""Published artifacts — the files an agent surfaces for preview.

When the agent produces something visual in its sandbox (an HTML report, a chart,
a code snippet), it *publishes* the file: the bytes are captured here, decoupled
from the sandbox's lifecycle, so the operator can preview them even after the
session is reaped. The bytes are **encrypted at rest** under the vault (they are
the operator's content); the metadata that lets the UI list and route to a
preview (conversation, title, content type, size) stays in the clear.

Keyed by ``conversation_id`` — not a foreign key, because an artifact can also
come from a stateless run (keyed by its run id), which is not a conversation row.
Every record carries the ``owner_id`` seam.
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel

from models._fields import new_id, utcnow


class Artifact(SQLModel, table=True):
    __tablename__ = "artifacts"

    id: str = Field(default_factory=new_id, primary_key=True)
    owner_id: str = Field(index=True)
    conversation_id: str = Field(index=True)
    run_id: str | None = None
    title: str
    filename: str
    content_type: str
    # Coarse rendering hint for the UI: "html" | "image" | "text" | "other".
    kind: str
    size: int
    # AEAD ciphertext of the file bytes (the source of truth).
    blob_enc: bytes
    created_at: datetime = Field(default_factory=utcnow, index=True)
