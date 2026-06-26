"""Conversation-scoped tool auto-approval grants.

A grant records the operator's decision to auto-approve a given (namespaced) tool's
deferred calls within one conversation, for a bounded window (the TTL). While a grant is
active the engine resolves that tool's approval requests without re-prompting; an expired
or absent grant falls back to the strict per-call approval default. Grants are operator
policy, not content — structural fields only, so nothing here is vault-sealed — and
owner-scoped like every record.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from models._fields import new_id, utcnow


class ApprovalGrant(SQLModel, table=True):
    __tablename__ = "approval_grants"
    # One grant per (owner, conversation, tool): re-granting refreshes its expiry.
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "conversation_id", "tool_name", name="uq_approval_grant_scope"
        ),
    )

    id: str = Field(default_factory=new_id, primary_key=True)
    owner_id: str = Field(index=True)
    conversation_id: str = Field(index=True)
    # The namespaced tool name auto-approved in this conversation (e.g. "corpus_retrieve").
    tool_name: str
    created_at: datetime = Field(default_factory=utcnow)
    # When the grant lapses back to strict per-call approval (UTC).
    expires_at: datetime
