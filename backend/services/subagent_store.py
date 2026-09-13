"""Reading and writing the sub-agent register.

One store over ``models/subagent.py``, and the only place rows of it are shaped. Four
readers depend on it agreeing with itself — the cap counts live sub-agents here, the wake
finds the parent here, the panel draws from here, and the parent's own ``subagent_read``
answers from here — so none of them keeps a count or a link of its own.

Everything the agent wrote is sealed on the way in and opened on the way out, the same as
a conversation's title: a task and a report are the agent's words about the operator's
work, and a database file lifted off disk should give up neither.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import Engine
from sqlmodel import Session, select

from core.db import in_session
from core.vault import Vault
from models.subagent import SubagentRecord
from services.subagents.launcher import SubagentView

logger = logging.getLogger(__name__)

#: The statuses a sub-agent is still *expected* to report from. Both count against the
#: operator's cap: a sub-agent parked on an approval has not reported, and the thing it is
#: waiting for is a person rather than a slot, so releasing its budget would let the model
#: pile up work behind a decision nobody has made yet.
#:
#: Only ``running`` is ever *written* — a row is opened at a launch and closed at an
#: ending, and the parked state in between is read off the live Run by
#: :meth:`SubagentStore.view`'s caller rather than persisted, because the Run is the thing
#: that actually knows. ``blocked`` is in the set anyway so that the one vocabulary answers
#: for both, and a future writer of it cannot silently stop counting.
LIVE_STATUSES: frozenset[str] = frozenset({"running", "blocked"})


class SubagentStore:
    def __init__(self, db_engine: Engine, vault: Vault) -> None:
        self._db = db_engine
        self._vault = vault

    async def record(
        self,
        *,
        subagent_id: str,
        owner_id: str,
        parent_conversation_id: str,
        child_conversation_id: str,
        run_id: str,
        parent_run_id: str | None,
        spec_name: str,
        handle: str,
        task: str,
        workspace_policy: str,
        workspace_key: str | None,
        delegation_id: str | None,
        workspace_kind: str | None = None,
        project_id: str | None = None,
    ) -> None:
        """Open a row for a sub-agent that has just been submitted.

        Written *after* the child's turn is composed, so a launch that failed on the way
        there leaves no row for a sub-agent that never ran — the panel would show a card
        that was never anything, and the cap would count a slot nothing holds.
        """
        row = SubagentRecord(
            id=subagent_id,
            owner_id=owner_id,
            parent_conversation_id=parent_conversation_id,
            child_conversation_id=child_conversation_id,
            run_id=run_id,
            parent_run_id=parent_run_id,
            spec_name=spec_name,
            handle=handle,
            task_enc=self._vault.encrypt_str(task),
            workspace_policy=workspace_policy,
            workspace_key=workspace_key,
            delegation_id=delegation_id,
            workspace_kind=workspace_kind,
            project_id=project_id,
        )

        def work(session: Session) -> None:
            session.add(row)

        await in_session(self._db, work)

    async def settle(
        self,
        subagent_id: str,
        *,
        status: str,
        summary: str | None = None,
        error: str | None = None,
        context_used: int | None = None,
        context_window: int | None = None,
    ) -> None:
        """Close a row out. Idempotent on a row already settled, because the two paths that
        can reach one — the run's terminal hook and an operator's cancel — can both fire for
        the same sub-agent and neither is worth losing the other's record over."""
        summary_enc = None if summary is None else self._vault.encrypt_str(summary)
        error_enc = None if error is None else self._vault.encrypt_str(error)

        def work(session: Session) -> None:
            row = session.get(SubagentRecord, subagent_id)
            if row is None:
                return
            row.status = status
            if summary_enc is not None:
                row.summary_enc = summary_enc
            if error_enc is not None:
                row.error_enc = error_enc
            if context_used is not None:
                row.context_used = context_used
            if context_window is not None:
                row.context_window = context_window
            row.ended_at = datetime.now(UTC)
            session.add(row)

        await in_session(self._db, work)

    async def get(self, subagent_id: str, owner_id: str) -> SubagentRecord | None:
        def work(session: Session) -> SubagentRecord | None:
            row = session.get(SubagentRecord, subagent_id)
            return row if row is not None and row.owner_id == owner_id else None

        return await in_session(self._db, work)

    async def by_handle(
        self, parent_conversation_id: str, handle: str, owner_id: str
    ) -> SubagentRecord | None:
        """The sub-agent a thread called ``handle`` — how the model's own two tools resolve.

        Scoped to the parent thread and not merely to the owner, because that is where the
        handle is unique and it is also the security boundary: an owner-wide lookup would
        let one thread's agent address another thread's sub-agent by guessing a plausible
        name, which is the sibling-injection hole the withheld-tool set closes on the other
        axis.

        Newest first where more than one row answers. Uniqueness is enforced at launch and
        not by the schema, so the honest tie-breaker is the one that matches what the model
        means: rows backfilled from an older build all took their spec's name, and a thread
        that launched two ``explorer``s before handles existed has two rows called
        ``explorer`` with no launch-time choice to tell them apart. The most recent is the
        one a parent asking about ``explorer`` is asking about.
        """

        def work(session: Session) -> SubagentRecord | None:
            rows = session.exec(
                select(SubagentRecord)
                .where(SubagentRecord.owner_id == owner_id)
                .where(SubagentRecord.parent_conversation_id == parent_conversation_id)
                .where(SubagentRecord.handle == handle)
            ).all()
            return max(rows, key=lambda row: row.started_at, default=None)

        return await in_session(self._db, work)

    async def handles_for_parent(
        self, parent_conversation_id: str, owner_id: str
    ) -> set[str]:
        """Every handle already taken in a thread — what a launch makes itself unique against.

        Finished sub-agents included, and that is the point: a parent can read a settled
        sub-agent's report back by name long after it ended, so re-using its handle for a
        new one would silently redirect that read to different work. A handle is unique for
        the life of the thread, not for the life of the run.
        """

        def work(session: Session) -> set[str]:
            rows = session.exec(
                select(SubagentRecord.handle)  # type: ignore[call-overload]
                .where(SubagentRecord.owner_id == owner_id)
                .where(SubagentRecord.parent_conversation_id == parent_conversation_id)
            ).all()
            return {handle for handle in rows if handle}

        return await in_session(self._db, work)

    async def by_run(self, run_id: str) -> SubagentRecord | None:
        """The sub-agent a Run belongs to, or None for an ordinary run.

        How the terminal hook recognises one of ours without the substrate having to carry
        a flag for it: every run reaches that hook, and this answers "was that a sub-agent"
        from the register rather than from anything stamped on the Run.
        """

        def work(session: Session) -> SubagentRecord | None:
            return session.exec(
                select(SubagentRecord).where(SubagentRecord.run_id == run_id)
            ).first()

        return await in_session(self._db, work)

    async def for_parent(
        self, parent_conversation_id: str, owner_id: str, *, live_only: bool = False
    ) -> list[SubagentRecord]:
        """Every sub-agent a thread launched, newest first — the panel's backfill."""

        def work(session: Session) -> list[SubagentRecord]:
            query = (
                select(SubagentRecord)
                .where(SubagentRecord.owner_id == owner_id)
                .where(SubagentRecord.parent_conversation_id == parent_conversation_id)
            )
            if live_only:
                query = query.where(SubagentRecord.status.in_(LIVE_STATUSES))  # type: ignore[attr-defined]
            rows = session.exec(query).all()
            return sorted(rows, key=lambda row: row.started_at, reverse=True)

        return await in_session(self._db, work)

    async def live(
        self, owner_id: str, *, parent_conversation_id: str | None = None
    ) -> list[SubagentRecord]:
        """Every sub-agent still expected to report — what the operator's cap counts."""

        def work(session: Session) -> list[SubagentRecord]:
            query = (
                select(SubagentRecord)
                .where(SubagentRecord.owner_id == owner_id)
                .where(SubagentRecord.status.in_(LIVE_STATUSES))  # type: ignore[attr-defined]
            )
            if parent_conversation_id is not None:
                query = query.where(
                    SubagentRecord.parent_conversation_id == parent_conversation_id
                )
            rows = session.exec(query).all()
            return sorted(rows, key=lambda row: row.started_at)

        return await in_session(self._db, work)

    async def delete_for_parent(self, parent_conversation_id: str, owner_id: str) -> None:
        """Forget every sub-agent a thread launched, because the thread is gone.

        The rows are only ever read *by* parent, so one whose parent has been deleted is
        unreachable rather than merely unlisted — and it would still be counted by the cap
        if it were somehow left live. Deleting them is the same reasoning as the thread's
        tasks, plan and View history going with it: they all restate work that was asked
        for in a conversation that no longer exists.
        """

        def work(session: Session) -> None:
            rows = session.exec(
                select(SubagentRecord)
                .where(SubagentRecord.owner_id == owner_id)
                .where(SubagentRecord.parent_conversation_id == parent_conversation_id)
            ).all()
            for row in rows:
                session.delete(row)

        await in_session(self._db, work)

    async def reconcile_stranded(self) -> int:
        """Close out every row left live by a process that died, at startup.

        A sub-agent's run lives in the process, so a row still ``running`` after a restart
        describes work that stopped when the process did. Left alone it would sit on
        ``running`` forever — counting against the cap, showing a spinner in the panel, and
        promising the parent a report that is never coming. Calling it ``cancelled`` is both
        true and the honest thing to show the operator.
        """

        def work(session: Session) -> int:
            rows = session.exec(
                select(SubagentRecord).where(SubagentRecord.status.in_(LIVE_STATUSES))  # type: ignore[attr-defined]
            ).all()
            for row in rows:
                row.status = "cancelled"
                row.ended_at = row.ended_at or datetime.now(UTC)
                session.add(row)
            return len(rows)

        stranded = await in_session(self._db, work)
        if stranded:
            logger.info("subagents: reconciled %s stranded run(s) to cancelled", stranded)
        return stranded

    def view(
        self,
        row: SubagentRecord,
        *,
        status: str | None = None,
        context_used: int | None = None,
        context_window: int | None = None,
    ) -> SubagentView:
        """A row as its readers see it, unsealed.

        ``status`` and the two context figures may be overridden by a caller holding the
        *live* Run, whose in-flight numbers are newer than anything written here — the
        stored ones exist for a sub-agent that finished before anyone looked.
        """
        return SubagentView(
            subagent_id=row.id,
            conversation_id=row.child_conversation_id,
            run_id=row.run_id,
            name=row.spec_name,
            # `or row.spec_name` for a row written before the column existed and missed the
            # migration's backfill — a card with no name to address it by is worse than one
            # named after its spec, which is what every such row was called anyway.
            handle=row.handle or row.spec_name,
            task=self._vault.decrypt_str(row.task_enc),
            status=status or row.status,
            summary=(
                None if row.summary_enc is None else self._vault.decrypt_str(row.summary_enc)
            ),
            error=None if row.error_enc is None else self._vault.decrypt_str(row.error_enc),
            context_used=context_used if context_used is not None else row.context_used,
            context_window=(
                context_window if context_window is not None else row.context_window
            ),
            started_at=row.started_at,
            ended_at=row.ended_at,
        )
