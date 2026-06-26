"""Conversation-scoped tool auto-approval grants over the ``approval_grants`` table.

When the operator approves a deferred tool call with the "allow for this conversation"
option, a grant is recorded here; while it is active (non-expired) the engine
auto-approves that tool's deferred calls in that conversation instead of re-prompting.
Grants are bounded by a TTL and are visible + revocable. Owner-scoped like every record.

A grant is operator policy, not secret content, so it is stored in the clear (no vault
sealing). Expiry is enforced in Python after normalizing to UTC, so the round-trip
through SQLite (which may drop tzinfo) can't make a naive/aware comparison raise.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, delete
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from core.db import in_session
from models._fields import new_id, utcnow
from models.approval_grant import ApprovalGrant


@dataclass(frozen=True)
class GrantInfo:
    """A live grant, for the operator's visible/revocable list."""

    tool_name: str
    expires_at: datetime


def _as_utc(value: datetime) -> datetime:
    """A DB-read datetime as tz-aware UTC (SQLite may hand it back naive)."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def covered_by_grant(tool_name: str | None, active: set[str]) -> bool:
    """Whether a deferred call to ``tool_name`` is covered by a conversation's active
    grant set. The single rule consulted by both the engine's park-time split and the
    approve route's resume-time re-validation, so the two paths can't diverge (a future
    refinement — e.g. per-argument scoping — lands here once)."""
    return tool_name is not None and tool_name in active


class ApprovalGrantStore:
    def __init__(self, db_engine: Engine, ttl_s: float) -> None:
        self._db = db_engine
        self._ttl = timedelta(seconds=ttl_s)

    async def grant(self, owner_id: str, conversation_id: str, tool_name: str) -> datetime:
        """Record (or refresh) a conversation-scoped auto-approval for ``tool_name``.
        Returns the new expiry."""
        expires_at = utcnow() + self._ttl

        def work(session: Session) -> datetime:
            # Atomic get-or-create over uq_approval_grant_scope: a plain select-then-insert
            # races two concurrent approvals of the same tool into a duplicate-insert
            # IntegrityError, so push the conflict resolution into the DB — insert, or
            # refresh the existing row's expiry on conflict.
            stmt = (
                sqlite_insert(ApprovalGrant)
                .values(
                    id=new_id(),
                    owner_id=owner_id,
                    conversation_id=conversation_id,
                    tool_name=tool_name,
                    created_at=utcnow(),
                    expires_at=expires_at,
                )
                .on_conflict_do_update(
                    index_elements=["owner_id", "conversation_id", "tool_name"],
                    set_={"expires_at": expires_at},
                )
            )
            session.execute(stmt)
            return expires_at

        return await in_session(self._db, work)

    async def list(self, owner_id: str, conversation_id: str) -> list[GrantInfo]:
        """Live (non-expired) grants in this conversation, for the revocable view."""
        if not conversation_id:
            return []
        now = utcnow()

        def work(session: Session) -> list[GrantInfo]:
            rows = session.exec(
                select(ApprovalGrant)
                .where(ApprovalGrant.owner_id == owner_id)
                .where(ApprovalGrant.conversation_id == conversation_id)
            ).all()
            live: list[GrantInfo] = []
            expired_ids: list[str] = []
            # Expiry is compared in Python (tz-normalized) so a SQLite-naive round-trip
            # can't break the comparison; a SQL `WHERE expires_at > now` would. Lapsed
            # rows are pruned opportunistically on read so the table can't grow without
            # bound — a bulk delete by id, idempotent under a concurrent prune.
            for r in rows:
                if _as_utc(r.expires_at) > now:
                    live.append(GrantInfo(tool_name=r.tool_name, expires_at=_as_utc(r.expires_at)))
                else:
                    expired_ids.append(r.id)
            if expired_ids:
                session.execute(delete(ApprovalGrant).where(ApprovalGrant.id.in_(expired_ids)))
            return live

        return await in_session(self._db, work)

    async def active(self, owner_id: str, conversation_id: str) -> set[str]:
        """The tool names with a live grant in this conversation (the engine's hot path)."""
        return {g.tool_name for g in await self.list(owner_id, conversation_id)}

    async def revoke(self, owner_id: str, conversation_id: str, tool_name: str) -> None:
        """Drop a conversation's grant for ``tool_name`` — the next call asks again."""

        def work(session: Session) -> None:
            row = session.exec(
                select(ApprovalGrant)
                .where(ApprovalGrant.owner_id == owner_id)
                .where(ApprovalGrant.conversation_id == conversation_id)
                .where(ApprovalGrant.tool_name == tool_name)
            ).first()
            if row is not None:
                session.delete(row)

        await in_session(self._db, work)
