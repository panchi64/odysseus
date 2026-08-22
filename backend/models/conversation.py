"""Conversation persistence schema.

A conversation owns a **tree** of messages, not a flat list. Each message stores
**both** a serialized Pydantic AI ``ModelMessage`` blob (full fidelity, so a cold
session rehydrates exactly) **and** a thin projection (kind + text) for listing
and search. The projection is derived, never authoritative.

The tree is what makes regenerate / edit / rewind possible. Every message points
at its predecessor via ``parent_id``; **messages sharing a parent are alternative
continuations — versions.** Regenerating an answer adds a sibling under the same
user request; editing a user turn adds a sibling under the same parent. The
conversation's ``active_leaf_id`` is the tip of the path the operator is currently
viewing — walking it parent-by-parent to the root yields the active history, the
flat list the agent actually runs against. ``seq`` is a per-conversation,
monotonically increasing creation counter; it no longer implies linear order, but
it gives siblings a stable version ordering (oldest first) and keeps writes
collision-free across branches.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel

from models._fields import new_id, utcnow


class Conversation(SQLModel, table=True):
    __tablename__ = "conversations"

    id: str = Field(default_factory=new_id, primary_key=True)
    owner_id: str = Field(index=True)
    # AEAD ciphertext of the thread's title. It is user content — an auto-generated
    # summary of the operator's own first message, and the most revealing single line a
    # thread has — so it is sealed like every peer entity's title (XC-SEC-3). Null for an
    # untitled thread.
    title_enc: str | None = None
    # The pre-encryption cleartext title. Kept **only** for rows written before the title
    # was sealed: reads prefer `title_enc` and fall back here, and the startup backfill
    # seals each remaining value and nulls this out (services/sealing.py). Nothing writes
    # it any more, so it is null on every new row and drains to null on every old one — a
    # migration can't do the sealing itself, because it runs before unlock with no key.
    title: str | None = None
    # Tip of the path the operator is currently viewing. Walking it parent-by-parent
    # to the root is the active history. Null only for an empty conversation; a
    # cold load that finds it dangling falls back to the deepest leaf by seq.
    active_leaf_id: str | None = None
    # The model the active path last ran on (its most recent answer's model_name),
    # denormalized so the listing reads it without opening a message blob. Kept in
    # step with active_leaf_id by the write-behind store; structural metadata, not
    # user content, so it stays in the clear. Null until the first answer.
    model: str | None = None
    # A scratch conversation that the listing hides — used by the side-by-side
    # compare surface, where each pane is a throwaway thread the operator never
    # meant to keep. Still a fully real conversation (readable, resumable, branch-
    # able by id); it's only omitted from the conversation list and the count.
    ephemeral: bool = Field(default=False)
    # Per-conversation override of the global conversation auto-compaction toggle (folding
    # older turns into a utility-model summary once the context footprint nears the model's
    # window): null inherits the operator default, True/False forces it on/off for this
    # thread. Policy, not user content, so it stays in the clear — like `model`/`ephemeral`.
    auto_compact_override: bool | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Message(SQLModel, table=True):
    __tablename__ = "messages"
    # The creation counter is unique per conversation — a double-insert (e.g. a
    # retried write that partly landed) fails loudly instead of silently
    # duplicating. seq no longer implies linear order (the tree does), only the
    # order in which rows were created.
    __table_args__ = (UniqueConstraint("conversation_id", "seq", name="uq_message_conv_seq"),)

    id: str = Field(default_factory=new_id, primary_key=True)
    conversation_id: str = Field(index=True, foreign_key="conversations.id")
    # The message this one follows. Null = a root (the conversation's first
    # message). Messages sharing a parent are alternative continuations = versions.
    parent_id: str | None = Field(default=None, index=True, foreign_key="messages.id")
    seq: int = Field(index=True)  # monotonic creation counter, from 0; orders siblings
    kind: str  # "request" | "response"
    # Operator's pin on this turn — a durable bookmark surfaced in the projection.
    # Set on the turn's branch node (the user request, or an assistant's first response).
    pinned: bool = Field(default=False)
    text: str  # projection for listing/search
    blob: str  # one serialized ModelMessage (JSON) for resume fidelity
    # Upload ids the operator attached to this turn (a user request). The blob carries
    # only a compact marker for them — never the file bytes/text — so the file is not
    # replayed into context on every later turn (the agent pulls it from the corpus on
    # demand); these ids are the durable link the UI renders as chips and a regenerate
    # re-resolves to re-supply the file for the active turn. Opaque ids, so in the clear.
    attachment_ids: list[str] = Field(sa_column=Column(JSON, nullable=False, default=list))
    # Set on an assistant turn's branch node when the run backing it ended
    # `outcome: "blocked"` (a usage/loop/context/time bound, not a normal finish) —
    # the human-readable reason (`Run.detail`), so a reload shows the same
    # persistent stop marker the live stream rendered. Null for every other turn.
    blocked_reason: str | None = None
    # A conversation-compaction checkpoint: this node's blob is a utility-model summary
    # of everything on its path up to and including `compacted_through`, folded in once
    # the context footprint neared the model's window. Nothing is deleted — the summarized
    # turns stay in the tree and in the operator's transcript; the checkpoint only changes
    # what the *model* replays (see `ConversationStore.model_history`). A checkpoint row
    # deliberately carries an empty `text`, so it contributes no embedding, no cross-chat
    # search hit, and no listing preview — the summary lives only in the sealed blob.
    compacted: bool = Field(default=False)
    compacted_through: str | None = None
    # Semantic-search vector over `text`, encrypted at rest like the projection it
    # embeds. Null when the message has no searchable text (tool/reasoning-only
    # turns) or the embedder was unavailable when it was persisted — such a message
    # falls back to keyword-only recall, the same degrade memories use (EMB-2). The
    # model/dim record the embedding space so vectors are only ever compared within it.
    embedding_enc: str | None = None
    embedding_model: str | None = None
    embedding_dim: int | None = None
    created_at: datetime = Field(default_factory=utcnow)
