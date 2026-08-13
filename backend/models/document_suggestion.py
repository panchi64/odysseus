"""Document suggestion schema (`DOC-3`) — a *proposed* change that has not been applied.

This is the one thing ``DocumentVersion`` cannot express. A version is an append-only
record of a change that **already happened**; a suggestion is a change the AI is offering
that the operator has not agreed to yet. So it needs its own rows, with their own
lifecycle, and **only accepting one mints a version**.

The shape is a **set of changes**, not a single patch:

- A :class:`DocumentSuggestionSet` is one AI pass over one document — "here are five
  things I'd change". It groups, it doesn't decide.
- A :class:`DocumentSuggestionChange` is one **anchored span** inside that pass:
  replace this exact stretch of text with that one. Each carries its own status, so the
  operator accepts change 2 and 4, rejects 1, and leaves 3 for later — the change-by-change
  review the requirement asks for. The anchor is the span *text*, not an offset, so it
  re-locates itself against whatever the document says at accept time (and refuses, rather
  than corrupting, when the document has moved underneath it).

At-rest posture mirrors ``models/document``: everything that **is** content — the spans
being replaced, the replacement text, the plain-language explanations — is sealed under
the vault. Structure the DB has to sort and filter on stays in the clear: ``owner_id``,
the set/document links, the ordinal, the status, the minted version number, timestamps.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlmodel import Field, SQLModel

from models._fields import new_id, utcnow


class SuggestionStatus(StrEnum):
    """Where a single proposed change stands (`DOC-3`). A plain string column carries it —
    matching ``DocumentVersionOrigin`` — with this enum as the in-code vocabulary.

    ``PENDING`` is the only state in which a change can still be applied; the other two are
    terminal, and a set is fully reviewed once none of its changes are pending."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class DocumentSuggestionSet(SQLModel, table=True):
    __tablename__ = "document_suggestion_sets"

    id: str = Field(default_factory=new_id, primary_key=True)
    owner_id: str = Field(index=True)
    document_id: str = Field(index=True)
    # The conversation the pass was produced in, when it came from a chat (null when some
    # non-agent caller proposed it). Provenance, not content — clear, like Document's.
    conversation_id: str | None = Field(default=None, index=True)
    # AEAD ciphertext of the pass's plain-language summary ("tightened the intro, fixed the
    # dates"). It describes the document's content, so it's sealed like the content.
    summary_enc: str
    created_at: datetime = Field(default_factory=utcnow, index=True)


class DocumentSuggestionChange(SQLModel, table=True):
    __tablename__ = "document_suggestion_changes"

    id: str = Field(default_factory=new_id, primary_key=True)
    owner_id: str = Field(index=True)
    set_id: str = Field(index=True)
    # Denormalized from the set so "what's pending on this document?" is one indexed read
    # rather than a join — the question the review UI asks on every open.
    document_id: str = Field(index=True)
    # Position within the pass, in the order the AI produced them (0-based). Presentation
    # order only — application order is recomputed from the live body at accept time.
    ordinal: int
    # Sealed: the anchor span to find, and the text to put in its place. The anchor must
    # match exactly one span of the document body or the change refuses to apply.
    old_text_enc: str
    new_text_enc: str
    # Sealed: why the AI proposes this change, shown beside the diff in the review UI.
    explanation_enc: str
    # pending | accepted | rejected — the review state. Policy, not content, and indexed
    # because listing pending changes is the hot read.
    status: str = Field(default=SuggestionStatus.PENDING, index=True)
    # The DocumentVersion this change minted when it was accepted; null while it is pending
    # and forever if it is rejected. The clear link from "the operator agreed" to "the
    # document changed" — a rejected change leaves no trace in the version history at all.
    version: int | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow)
    # When the operator accepted or rejected it (null while pending).
    decided_at: datetime | None = Field(default=None)
