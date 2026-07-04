"""Documents schema — an editable document plus its versioned edit history.

A document is a piece of the operator's own writing the library lets them create,
edit, archive, and restore (`DOC-1`); its body is also the source text indexed into
the knowledge corpus so the agent can retrieve it. Every change snapshots a new
**version** stamped with its origin — the operator, the AI, or an extraction
pipeline (`DOC-2`) — and any version is restorable.

At-rest posture mirrors memory and the corpus chunks: the content the document
*is* — its ``title`` and ``body`` — is **encrypted at rest** under the vault (and
the same sealed snapshot on every version row). Structural metadata stays in the
clear so the DB can order the library, segregate archived rows, and walk a
document's version history: ``owner_id``, timestamps, the ``archived`` flag, the
detected ``doc_type``/``language`` (display hints, not content), and a version's
monotonic ``version`` number and ``origin``.

Versions are **append-only full snapshots**, not diffs: at single-operator scale,
with everything sealed at rest, a snapshot makes restore a copy rather than a diff
replay — the same reasoning (brute-force over the sealed working set, D18) that the
rest of the recall path takes.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlmodel import Field, SQLModel

from models._fields import new_id, utcnow


class DocumentVersionOrigin(StrEnum):
    """Who authored a version snapshot (`DOC-2`). A plain string column carries it,
    matching how the corpus's ``status`` is a plain str — no DB enum, so SQLite +
    Alembic stay simple — with this enum as the in-code vocabulary."""

    USER = "user"
    AI = "ai"
    EXTRACTION = "extraction"


class Document(SQLModel, table=True):
    __tablename__ = "documents"

    id: str = Field(default_factory=new_id, primary_key=True)
    owner_id: str = Field(index=True)
    # The conversation that created this document, when it was born in a chat (null for a
    # document created straight from the library UI). Provenance, not content, so it stays
    # in the clear and indexed: it drives whether the agent may edit the document without
    # asking (a doc it created in *this* thread is ungated; a library/other-thread doc gates
    # the first edit) and seeds the chat View with the thread's documents.
    conversation_id: str | None = Field(default=None, index=True)
    # AEAD ciphertext of the title + body (the document's content, the source of truth
    # — the body is also what the corpus indexes).
    title_enc: str
    body_enc: str
    # Display hints detected from the body, kept in the clear (not content): a coarse
    # type ("markdown" | "code" | "text") and a best-effort human-language code.
    doc_type: str = Field(default="text")
    language: str | None = None
    # DOC-1 archive is a soft flag (restorable), not a delete; indexed so the library
    # can list active and archived separately.
    archived: bool = Field(default=False, index=True)
    created_at: datetime = Field(default_factory=utcnow, index=True)
    updated_at: datetime = Field(default_factory=utcnow)


class DocumentVersion(SQLModel, table=True):
    __tablename__ = "document_versions"

    id: str = Field(default_factory=new_id, primary_key=True)
    owner_id: str = Field(index=True)
    document_id: str = Field(index=True)
    # Monotonic per document (1-based), giving versions a stable order to restore by.
    version: int
    # Sealed snapshot of the content at this version (restore copies it back).
    title_enc: str
    body_enc: str
    # Clear display-hint snapshot, so a restore brings back the right type/language.
    doc_type: str = Field(default="text")
    language: str | None = None
    # user | ai | extraction — who produced this version (DOC-2). A plain str column;
    # DocumentVersionOrigin is the in-code vocabulary.
    origin: str = Field(default=DocumentVersionOrigin.USER, index=True)
    created_at: datetime = Field(default_factory=utcnow)
