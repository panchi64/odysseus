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

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from models._fields import new_id, utcnow


class Conversation(SQLModel, table=True):
    __tablename__ = "conversations"

    id: str = Field(default_factory=new_id, primary_key=True)
    owner_id: str = Field(index=True)
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
    created_at: datetime = Field(default_factory=utcnow)
