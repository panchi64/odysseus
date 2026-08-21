"""Reading and writing the ``research`` table, and sealing what goes in it.

Deliberately not a service class. The research surface has no service layer (it mirrors
``routes/tasks.py``: the router drives the pipeline core directly), and inventing one here
would add a hop that owns no decisions. What this module *is* is the persistence half of
that router, split out because a router file should not also be the place the encryption
of a stored plan is decided.

Three things live here:

- **The seal.** A research entry's question, clarifying questions, plan and report are
  encrypted at rest; ``status``, timestamps and the run id are clear (they are how a row
  is found and how the surface renders a listing without unsealing anything).
- **The row reads/writes**, including the two guarded transitions — staging a launch and
  reverting one whose Run never got submitted.
- **The terminal write**, which runs as its own task so persisting a run's outcome is
  never at risk of the same cancellation it is recording.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine
from sqlmodel import Session, select

from core.db import in_session
from core.vault import Vault
from models._fields import utcnow
from models.research import ResearchRun, ResearchStatus
from research import ResearchPlan, ResearchResult
from runs import Run, RunStatus

# --- the seal ------------------------------------------------------------------------


def encode_list(vault: Vault, values: list[str] | None) -> str | None:
    if not values:
        return None
    return vault.encrypt_str(json.dumps(values))


def decode_list(vault: Vault, enc: str | None) -> list[str] | None:
    if enc is None:
        return None
    return json.loads(vault.decrypt_str(enc))


def encode_plan(vault: Vault, plan: ResearchPlan | None) -> str | None:
    if plan is None:
        return None
    return vault.encrypt_str(plan.model_dump_json())


def decode_plan(vault: Vault, enc: str | None) -> ResearchPlan | None:
    if enc is None:
        return None
    return ResearchPlan.model_validate_json(vault.decrypt_str(enc))


# --- rows ----------------------------------------------------------------------------


async def get_owned(engine: Engine, owner_id: str, research_id: str) -> ResearchRun | None:
    """The row, if this owner has it. ``None`` covers both "not yours" and "not there" —
    the caller answers 404 either way, so the two stay indistinguishable."""

    def work(session: Session) -> ResearchRun | None:
        row = session.get(ResearchRun, research_id)
        if row is None or row.owner_id != owner_id:
            return None
        return row

    return await in_session(engine, work)


async def find_by_run(engine: Engine, run_id: str) -> ResearchRun | None:
    """The research row driven by ``run_id``, if any — used by the research manifest's
    run-terminal notifier to link a run's outcome back to its research entity without a
    second app.state mapping (a plain indexed lookup, off the hot path)."""

    def work(session: Session) -> ResearchRun | None:
        return session.exec(select(ResearchRun).where(ResearchRun.run_id == run_id)).first()

    return await in_session(engine, work)


async def mark_running(
    engine: Engine, research_id: str, *, run_id: str, started_at: datetime
) -> None:
    def work(session: Session) -> None:
        row = session.get(ResearchRun, research_id)
        if row is None:
            return
        # Guarded, not unconditional. `start` commits this *before* submitting, so the run
        # can no longer reach terminal ahead of it — but the guard still earns its place
        # against a second `start` on a row that has already launched: only stamp
        # run_id/started_at when no launch has been recorded yet (never clobber an
        # already-recorded run), and only promote draft -> running; never regress an
        # already-finalized status (done/error/cancelled) back to "running".
        if row.run_id is None:
            row.run_id = run_id
            row.started_at = started_at
        if row.status == ResearchStatus.DRAFT.value:
            row.status = ResearchStatus.RUNNING.value
        session.add(row)

    await in_session(engine, work)


async def revert_launch(engine: Engine, research_id: str, *, run_id: str) -> None:
    """Undo a `mark_running` whose run never got submitted, returning the row to `draft`
    so the operator can retry. Scoped to the run id this call staged, so a row that has
    since been legitimately relaunched is left alone."""

    def work(session: Session) -> None:
        row = session.get(ResearchRun, research_id)
        if row is None or row.run_id != run_id:
            return
        row.run_id = None
        row.started_at = None
        if row.status == ResearchStatus.RUNNING.value:
            row.status = ResearchStatus.DRAFT.value
        session.add(row)

    await in_session(engine, work)


async def set_conversation_id_if_absent(
    engine: Engine, research_id: str, conversation_id: str
) -> bool:
    """Claim the continue-in-chat conversation for this entry, returning whether this
    call is the one that claimed it. The check and the write share a session, so two
    concurrent continues can't both seed a conversation."""

    def work(session: Session) -> bool:
        row = session.get(ResearchRun, research_id)
        if row is None or row.conversation_id is not None:
            return False
        row.conversation_id = conversation_id
        session.add(row)
        return True

    return await in_session(engine, work)


# --- the terminal write ---------------------------------------------------------------


@dataclass
class RunOutcome:
    """What the orchestrate closure learned before its Run reached terminal — read by the
    finalize task once the terminal-transition waiter resolves. Set on every path except a
    genuine cancellation (there, neither is set and the finalizer falls back to
    ``run.status``/``run.error`` alone)."""

    result: ResearchResult | None = None
    error: str | None = None


async def finalize(
    engine: Engine,
    vault: Vault,
    research_id: str,
    waiter: asyncio.Future[Run],
    outcome: RunOutcome,
) -> None:
    """Await the Run's terminal transition, then persist the report/stats/status it
    settled at. Runs as its own background task (not inside the orchestrator's own,
    potentially-cancelled task) so persisting is never itself at risk of being interrupted
    by the same cancellation it's recording."""
    run = await waiter

    def work(session: Session) -> None:
        row = session.get(ResearchRun, research_id)
        if row is None:
            return
        row.finished_at = utcnow()
        if run.status is RunStatus.done and outcome.result is not None:
            row.status = ResearchStatus.DONE.value
            row.report_enc = vault.encrypt_str(outcome.result.report)
            row.stats = {
                "duration_s": outcome.result.duration_s,
                "rounds": outcome.result.rounds,
                "sources": outcome.result.sources,
                "queries": outcome.result.queries,
                "model": outcome.result.model,
            }
        elif run.status is RunStatus.cancelled:
            row.status = ResearchStatus.CANCELLED.value
        else:
            # error (SearchUnavailableError included, DR-4.1) or blocked — the Run
            # substrate's wall-clock/inactivity bounds stop a run via `run.block(detail)`,
            # which records the operator-legible reason on `run.detail`, not `run.error` —
            # so the report field carries the clear message either way, never left empty.
            message = (
                outcome.error
                or run.error
                or run.detail
                or "research failed for an unknown reason"
            )
            row.status = ResearchStatus.ERROR.value
            row.report_enc = vault.encrypt_str(message)
        session.add(row)

    await in_session(engine, work)
