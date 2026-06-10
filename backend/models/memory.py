"""Long-term memory schema.

A memory is a fact or preference the operator wants recalled across
conversations. Recall is **by meaning** with a keyword fallback (`MEM-2`), so a
memory carries its embedding alongside its text.

Everything that derives from the memory's content is **encrypted at rest** under
the vault: the ``content`` itself (source of truth) and the ``embedding`` vector
(embeddings are invertible enough to leak the text, so they are sealed too —
this is why recall is brute-force-in-Python over the decrypted working set rather
than an in-DB plaintext ANN index; see decision D18). Structural metadata
(owner, timestamps, pinned, embedding provenance) stays in the clear so the DB
can order the timeline and segregate stale embeddings.

The embedding's **model + dimension are recorded** (`EMB-2`): when the operator
changes the embedding model, existing vectors are a different shape/space, so
recall can re-embed or skip them rather than compare across incompatible spaces.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


def _new_id() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(UTC)


class Memory(SQLModel, table=True):
    __tablename__ = "memories"

    id: str = Field(default_factory=_new_id, primary_key=True)
    owner_id: str = Field(index=True)
    # AEAD ciphertext of the memory text (the source of truth).
    content_enc: str
    # AEAD ciphertext of the embedding (a JSON float array); None when the
    # embedding capability was unavailable at write time (keyword-only recall).
    embedding_enc: str | None = None
    # Embedding provenance for EMB-2: which model/space produced the vector.
    embedding_model: str | None = None
    embedding_dim: int | None = None
    # Pinned memories are always included in recall (MEM-4).
    pinned: bool = Field(default=False, index=True)
    created_at: datetime = Field(default_factory=_now, index=True)
    updated_at: datetime = Field(default_factory=_now)
