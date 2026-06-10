"""Conversation persistence schema.

A conversation owns an ordered list of messages. Each message stores **both** a
serialized Pydantic AI ``ModelMessage`` blob (full fidelity, so a cold session
rehydrates exactly) **and** a thin projection (kind + text) for listing and
search. The projection is derived, never authoritative.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


def _new_id() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(UTC)


class Conversation(SQLModel, table=True):
    __tablename__ = "conversations"

    id: str = Field(default_factory=_new_id, primary_key=True)
    owner_id: str = Field(index=True)
    title: str | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class Message(SQLModel, table=True):
    __tablename__ = "messages"
    # Ordering within a conversation is unique — a double-insert (e.g. a retried
    # write that partly landed) fails loudly instead of silently duplicating.
    __table_args__ = (UniqueConstraint("conversation_id", "seq", name="uq_message_conv_seq"),)

    id: str = Field(default_factory=_new_id, primary_key=True)
    conversation_id: str = Field(index=True, foreign_key="conversations.id")
    seq: int = Field(index=True)  # order within the conversation, from 0
    kind: str  # "request" | "response"
    text: str  # projection for listing/search
    blob: str  # one serialized ModelMessage (JSON) for resume fidelity
    created_at: datetime = Field(default_factory=_now)
