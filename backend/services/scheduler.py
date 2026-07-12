"""The task scheduler — the in-process tick loop behind `ScheduledTask` (`TASK-1..6`).

Single-instance, in-process: one asyncio task sleeps until the earliest
`next_run_at`, wakes, fires whatever is due, and sleeps again. It owns exactly the
scheduling mechanics — due-detection, non-overlap, lock-awareness, and recording each
firing as a `TaskRun` — and knows nothing about *how* a task actually runs: an agent
task is driven by an injected `executor` callable, a reminder by an injected `notify`
callable. Composing those two into "an agent task becomes an ordinary Run in a fresh
conversation" / "a reminder becomes a notification" is the caller's job (`app.py`,
wired by a later phase) — this module stays reusable by anything that can produce a
`TaskRunResult` for a `ScheduledTaskView`.

**Lock-aware** like `core.worker.WriteBehindWorker`: task prompts are encrypted, so
the loop parks (mirroring that worker's `_ready` wait) whenever the vault is locked
rather than erroring, and resumes on unlock. Because a locked/parked scheduler (or a
long boot) can leave a task's `next_run_at` sitting in the past, the loop's normal
due-check already doubles as the catch-up path: a tick fires an overdue task **once**
and immediately recomputes its schedule anchored on *now* (not on the stale
timestamp) — so a task never floods a burst of missed fires, whether the gap was a
locked vault, a restart, or just a slow executor.

**Non-overlap** (`TASK-5`): the loop tracks each task's in-flight execution as an
asyncio task in `_running`. A tick that finds a task's previous execution still
live records a `TaskRun` with outcome `skipped` instead of starting a second one, and
nudges that task's own schedule forward by a small poll floor rather than the
task's real cadence — so a busy task doesn't get re-detected-as-due (and re-skipped)
on every single loop iteration. The eventual real fire's own finalize overwrites that
placeholder with the actual next occurrence, anchored on when it actually settled.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from croniter import croniter
from sqlalchemy import Engine
from sqlmodel import Session, select

from core.db import in_session
from core.vault import Vault, VaultLocked
from models._fields import new_id, utcnow
from models.task import ScheduledTask, ScheduleType, TaskKind, TaskOutcome, TaskRun

logger = logging.getLogger(__name__)

# How soon a still-busy task is re-checked after a skip — deliberately much shorter
# than any real schedule, just enough to avoid a zero-wait busy loop while an
# overlap-in-progress task's own execution is still running.
_SKIP_RECHECK_S = 5.0

# The tick loop's own floor on how soon it re-checks after finding something already
# due — see `_wait_for`.
_MIN_POLL_S = 0.05


def _as_utc(value: datetime) -> datetime:
    """A DB-read datetime as tz-aware UTC. SQLite has no native datetime type — the
    dialect round-trips one as a naive value even though it was written tz-aware —
    so every due/ordering comparison against a fresh `utcnow()` normalizes first
    (mirrors `services/approval_grants.py`'s own `_as_utc`)."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


@dataclass(frozen=True)
class ScheduledTaskView:
    """A task's decrypted content, plus the metadata an executor/notifier needs —
    the shape passed into the two injected callables. Never persisted itself."""

    id: str
    owner_id: str
    kind: str  # TaskKind
    title: str
    prompt: str
    output: str  # TaskOutput
    pre_authorized: list[str]


@dataclass(frozen=True)
class TaskRunResult:
    """What an ``executor`` reports back for one agent-task execution. A ``notify``
    call for a reminder never produces one of these — the scheduler synthesizes an
    ``ok`` outcome itself unless ``notify`` raises."""

    outcome: str  # TaskOutcome, excluding "skipped" (the scheduler's own verdict)
    run_id: str | None = None
    conversation_id: str | None = None
    summary: str | None = None


TaskExecutor = Callable[[ScheduledTaskView], Awaitable[TaskRunResult]]
TaskNotifier = Callable[[ScheduledTaskView], Awaitable[None]]


def compute_next_run(
    schedule_type: str,
    *,
    anchor: datetime,
    run_at: datetime | None = None,
    every_seconds: float | None = None,
    cron_expr: str | None = None,
) -> datetime | None:
    """The next `next_run_at` for a schedule, given an anchor (the fire time it's
    counted forward from, for interval/cron — "anchored on last fire"). Deterministic
    and side-effect-free so both the scheduler and the future task-creation route can
    share it. Degrades to `None` ("never due") for a malformed schedule (missing
    interval, missing cron) rather than raising — the write-side route is where a bad
    schedule gets rejected, not this always-safe read path."""
    if schedule_type == ScheduleType.ONCE:
        # The single fire time itself; the caller disables the task once it has
        # actually fired rather than looping this function again.
        return run_at
    if schedule_type == ScheduleType.INTERVAL:
        if every_seconds is None or every_seconds <= 0:
            return None
        return anchor + timedelta(seconds=every_seconds)
    if schedule_type == ScheduleType.CRON:
        if not cron_expr:
            return None
        return croniter(cron_expr, anchor).get_next(datetime)
    return None  # ScheduleType.WEBHOOK (or an unrecognized value) — never time-due


class SchedulerService:
    def __init__(
        self,
        engine: Engine,
        vault: Vault,
        executor: TaskExecutor,
        notify: TaskNotifier,
        *,
        skip_recheck_s: float = _SKIP_RECHECK_S,
    ) -> None:
        self._engine = engine
        self._vault = vault
        self._executor = executor
        self._notify = notify
        self._skip_recheck_s = skip_recheck_s
        self._running: dict[str, asyncio.Task] = {}
        self._wake = asyncio.Event()
        self._stopping = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._stopping.clear()
        self._task = asyncio.create_task(self._run(), name="scheduler")

    async def stop(self) -> None:
        """Stop the tick loop and let any in-flight executions finish naturally —
        each one is responsible for its own `TaskRun` finalize, so cutting them off
        would strand a row `finished_at`-less forever."""
        self._stopping.set()
        self._wake.set()  # unstick a park on `_wait_unlocked`/`_wait_for`
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        if self._running:
            await asyncio.gather(*list(self._running.values()), return_exceptions=True)

    def wake(self) -> None:
        """Re-arm the sleep — call after any task create/update/delete so a changed
        `next_run_at` is picked up immediately rather than waiting out whatever the
        loop was already sleeping toward."""
        self._wake.set()

    # --- the tick loop ----------------------------------------------------------

    async def _run(self) -> None:
        while not self._stopping.is_set():
            if not await self._wait_unlocked():
                return
            now = utcnow()
            await self._tick(now)
            sleep_for = await self._sleep_duration()
            await self._wait_for(sleep_for)

    async def _wait_unlocked(self) -> bool:
        """Park while the vault is locked (task prompts are encrypted), mirroring
        `WriteBehindWorker._ready`. Returns False only if stopping while still
        locked — the loop should simply exit, not tick against an unreadable vault."""
        if self._vault.unlocked_event.is_set():
            return True
        stop_wait = asyncio.ensure_future(self._stopping.wait())
        unlock_wait = asyncio.ensure_future(self._vault.unlocked_event.wait())
        try:
            await asyncio.wait({stop_wait, unlock_wait}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            stop_wait.cancel()
            unlock_wait.cancel()
        return self._vault.unlocked_event.is_set()

    async def _wait_for(self, seconds: float | None) -> None:
        """Sleep until the earliest due task, a wake, or a stop — whichever first.
        `seconds is None` means "nothing scheduled": wait indefinitely for a wake/stop.
        A non-positive (or tiny) `seconds` is floored to `_MIN_POLL_S` rather than
        producing a zero-wait re-tick: a task just fired still has its own
        insert/execute/finalize/advance ahead of it on the DB, and a true busy-loop
        re-tick would re-discover it as "due" before that bookkeeping lands, logging
        a bogus overlap against itself. The floor is far below any real schedule
        granularity, so a genuine overlap (a slow execution still running when its
        own next occurrence comes due) is still detected well within it."""
        if self._stopping.is_set():
            self._wake.clear()
            return
        stop_wait = asyncio.ensure_future(self._stopping.wait())
        wake_wait = asyncio.ensure_future(self._wake.wait())
        waits = {stop_wait, wake_wait}
        if seconds is not None:
            waits.add(asyncio.ensure_future(asyncio.sleep(max(seconds, _MIN_POLL_S))))
        try:
            await asyncio.wait(waits, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for fut in waits:
                fut.cancel()
            await asyncio.gather(*waits, return_exceptions=True)
        self._wake.clear()

    async def _sleep_duration(self) -> float | None:
        earliest = await self._earliest_next_run()
        if earliest is None:
            return None
        return (earliest - utcnow()).total_seconds()

    async def _tick(self, now: datetime) -> None:
        for tid in [tid for tid, t in self._running.items() if t.done()]:
            self._running.pop(tid, None)
        due = await self._load_due(now)
        for task in due:
            await self._dispatch(task, now)

    # --- on-demand fire (manual run_now / an inbound webhook) ----------------------

    async def fire_now(self, task_id: str) -> str | None:
        """Fire ``task_id`` immediately — the manual ``run_now``/webhook entry point —
        through the exact same non-overlap path the tick loop's own due-detection uses
        (`_dispatch`), so an on-demand fire and a real due-tick can never double-run the
        same task. Returns the id of the `TaskRun` row this attempt recorded (fired or
        skipped), or ``None`` if no such task exists (the caller — the route — already
        checked ownership; this is a defensive re-check against a delete racing the
        request)."""

        def work(session: Session) -> ScheduledTask | None:
            return session.get(ScheduledTask, task_id)

        task = await in_session(self._engine, work)
        if task is None:
            return None
        return await self._dispatch(task, utcnow())

    # --- firing / skipping --------------------------------------------------------

    async def _dispatch(self, task: ScheduledTask, now: datetime) -> str:
        """Fire-or-skip ``task`` right now: a still-live previous execution (tracked in
        `_running`) records a `skipped` `TaskRun` instead of running twice; otherwise
        starts a tracked background execution. Returns the new `TaskRun`'s id either
        way. Synchronous up to the point `_running` is set (no `await` in between) —
        the same atomic check-and-claim discipline `RunRegistry.claim` uses — so the
        tick loop's due-detection and an on-demand `fire_now` can never both slip past
        the non-overlap check for the same task."""
        live = self._running.get(task.id)
        if live is not None and not live.done():
            return await self._skip(task, now)
        run_row_id = new_id()
        self._running[task.id] = asyncio.create_task(
            self._fire(task, now, run_row_id), name=f"scheduled-task:{task.id}"
        )
        return run_row_id

    async def _fire(self, task: ScheduledTask, fire_time: datetime, run_row_id: str) -> None:
        await self._insert_task_run(id=run_row_id, task_id=task.id, started_at=fire_time)
        try:
            try:
                view = self._decrypt_view(task)
                if task.kind == TaskKind.REMINDER:
                    await self._notify(view)
                    result = TaskRunResult(outcome=TaskOutcome.OK.value)
                else:
                    result = await self._executor(view)
            except Exception as exc:  # noqa: BLE001 — a bad task must never kill the loop
                logger.exception("scheduler: task %s execution failed", task.id)
                result = TaskRunResult(outcome=TaskOutcome.ERROR.value, summary=str(exc))
            finished = utcnow()
            if not await self._finalize_parked(
                run_row_id,
                finished_at=finished,
                outcome=result.outcome,
                run_id=result.run_id,
                conversation_id=result.conversation_id,
                summary=result.summary,
            ):
                # Stopping while the vault stayed locked through the whole park —
                # leave this run's row unfinalized and the task's own schedule
                # untouched, same as `WriteBehindWorker.stop()` leaving a locked
                # queue's items unflushed. A future boot's tick re-detects the task
                # as due (its `next_run_at` was never advanced) and re-fires it.
                return
            try:
                if task.schedule_type == ScheduleType.ONCE:
                    await self._advance(
                        task.id, last_run_at=finished, next_run_at=None, enabled=False
                    )
                else:
                    # Anchored on when the execution actually *settled*, not when it
                    # was launched — a slow run that outlives its own interval must
                    # schedule its next occurrence from now, never from a moment
                    # already further behind than a concurrent skip may have already
                    # advanced past.
                    next_run = compute_next_run(
                        task.schedule_type,
                        anchor=finished,
                        run_at=task.run_at,
                        every_seconds=task.every_seconds,
                        cron_expr=task.cron_expr,
                    )
                    await self._advance(task.id, last_run_at=finished, next_run_at=next_run)
            except Exception:  # noqa: BLE001 — a failed reschedule must never kill the loop
                # The advance never landed, so `next_run_at` still holds its stale
                # past value — the next tick simply re-detects the task as due and
                # re-fires it once the transient (a DB hiccup, a bad recompute) passes.
                logger.exception("scheduler: task %s schedule advance failed", task.id)
        finally:
            # Always release the in-flight claim, whatever path got us here — a task
            # id stranded in `_running` would turn every future due fire into a
            # `skipped` row until restart. The wake is what re-arms the sleep after
            # this task's schedule (maybe) changed; on the stopping-while-locked
            # early return it's harmless — the loop is already exiting.
            self._running.pop(task.id, None)
            self.wake()

    async def _skip(self, task: ScheduledTask, now: datetime) -> str:
        run_row_id = new_id()
        await self._insert_task_run(
            id=run_row_id,
            task_id=task.id,
            started_at=now,
            finished_at=now,
            outcome=TaskOutcome.SKIPPED.value,
        )
        # A plain recompute would hand a `once` task back its own fixed (already-past)
        # run_at forever — busy-looping until its one live execution finally settles.
        # A short poll floor sidesteps that without needing to special-case interval/
        # cron too (their own recompute already lands in the future off `now`).
        next_run = now + timedelta(seconds=self._skip_recheck_s)
        if task.schedule_type != ScheduleType.ONCE:
            computed = compute_next_run(
                task.schedule_type,
                anchor=now,
                run_at=task.run_at,
                every_seconds=task.every_seconds,
                cron_expr=task.cron_expr,
            )
            if computed is not None and computed > next_run:
                next_run = computed
        await self._advance(task.id, next_run_at=next_run)
        self.wake()
        return run_row_id

    def _decrypt_view(self, task: ScheduledTask) -> ScheduledTaskView:
        return ScheduledTaskView(
            id=task.id,
            owner_id=task.owner_id,
            kind=task.kind,
            title=self._vault.decrypt_str(task.title_enc),
            prompt=self._vault.decrypt_str(task.prompt_enc),
            output=task.output,
            pre_authorized=list(task.pre_authorized),
        )

    # --- persistence --------------------------------------------------------------

    async def _load_due(self, now: datetime) -> list[ScheduledTask]:
        # The due check itself runs in Python (not a SQL `WHERE next_run_at <= :now`)
        # so the naive round-trip `_as_utc` corrects for can't produce a wrong
        # comparison at the SQL layer — the same reasoning `approval_grants.py`
        # documents for its own expiry check.
        def work(session: Session) -> list[ScheduledTask]:
            return list(
                session.exec(
                    select(ScheduledTask)
                    .where(ScheduledTask.enabled.is_(True))
                    .where(ScheduledTask.next_run_at.is_not(None))
                ).all()
            )

        rows = await in_session(self._engine, work)
        return [row for row in rows if _as_utc(row.next_run_at) <= now]

    async def _earliest_next_run(self) -> datetime | None:
        def work(session: Session) -> list[datetime]:
            return list(
                session.exec(
                    select(ScheduledTask.next_run_at)
                    .where(ScheduledTask.enabled.is_(True))
                    .where(ScheduledTask.next_run_at.is_not(None))
                ).all()
            )

        rows = await in_session(self._engine, work)
        return min((_as_utc(r) for r in rows), default=None)

    async def _insert_task_run(self, **kwargs) -> None:
        def work(session: Session) -> None:
            session.add(TaskRun(**kwargs))

        await in_session(self._engine, work)

    async def _finalize_parked(
        self,
        run_row_id: str,
        *,
        finished_at: datetime,
        outcome: str,
        run_id: str | None,
        conversation_id: str | None,
        summary: str | None,
    ) -> bool:
        """Finalize a `TaskRun`, parking and retrying if the vault locks mid-flight
        (the operator locks it while an agent task is still executing, so
        `encrypt_str` on the summary raises `VaultLocked` after the executor has
        already returned) — mirrors `WriteBehindWorker`'s "a lock landing
        mid-handler is a park, not a failed attempt" rule rather than letting the
        exception escape the bare `asyncio.create_task` in `_tick` and strand this
        run's row and the task's own reschedule forever. Returns False only if the
        loop is stopping while the vault never unlocked again — same as
        `WriteBehindWorker.stop()` leaving a locked queue's items unflushed."""
        while True:
            try:
                await self._finalize_task_run(
                    run_row_id,
                    finished_at=finished_at,
                    outcome=outcome,
                    run_id=run_id,
                    conversation_id=conversation_id,
                    summary=summary,
                )
                return True
            except VaultLocked:
                logger.warning(
                    "scheduler: vault locked mid-finalize for task run %s — parking",
                    run_row_id,
                )
                if not await self._wait_unlocked():
                    return False

    async def _finalize_task_run(
        self,
        run_row_id: str,
        *,
        finished_at: datetime,
        outcome: str,
        run_id: str | None,
        conversation_id: str | None,
        summary: str | None,
    ) -> None:
        summary_enc = self._vault.encrypt_str(summary) if summary is not None else None

        def work(session: Session) -> None:
            row = session.get(TaskRun, run_row_id)
            if row is None:
                return
            row.finished_at = finished_at
            row.outcome = outcome
            row.run_id = run_id
            row.conversation_id = conversation_id
            row.summary_enc = summary_enc
            session.add(row)

        await in_session(self._engine, work)

    async def _advance(
        self,
        task_id: str,
        *,
        next_run_at: datetime | None,
        last_run_at: datetime | None = None,
        enabled: bool | None = None,
    ) -> None:
        def work(session: Session) -> None:
            row = session.get(ScheduledTask, task_id)
            if row is None:
                return
            row.next_run_at = next_run_at
            if last_run_at is not None:
                row.last_run_at = last_run_at
            if enabled is not None:
                row.enabled = enabled
            row.updated_at = utcnow()
            session.add(row)

        await in_session(self._engine, work)
