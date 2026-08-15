"""The scheduled-tasks surface — CRUD, manual fire, run history, and the inbound
webhook trigger over :class:`~models.task.ScheduledTask`/``TaskRun`` (`TASK-1..6`,
`AE-3.2`/`AE-3.5`).

No dedicated service layer exists yet for this surface (unlike documents/gallery/etc):
this router reads/writes the two tables directly, the same
``core.db.in_session`` primitive every service uses, and defers to
:class:`~services.scheduler.SchedulerService` only for the tick-loop-shaped
mechanics (on-demand fire, non-overlap, wake). Out-shapes are camelCase, like the
app's other newer surfaces (documents/gallery/corpus/notifications).

``POST /tasks/hooks/{token}`` is the one auth-EXEMPT route here (``core/auth.py``
matches ``/tasks/hooks/`` exactly, mirroring the ``/previews`` token-gated-subtree
pattern) — the per-task unguessable ``webhook_token`` **is** the credential, compared
in constant time against every webhook-type task rather than resolved by an indexed
equality lookup, so an inbound caller's timing can't narrow down a valid token.
"""

from __future__ import annotations

import secrets
from datetime import datetime

from croniter import croniter
from fastapi import APIRouter, HTTPException, Query, Request
from sqlmodel import Session, select

from core.db import in_session
from core.vault import Vault
from models._fields import utcnow
from models.task import (
    ScheduledTask,
    ScheduleType,
    TaskKind,
    TaskOutput,
    TaskRun,
    new_webhook_token,
)
from routes import deps
from routes.camel import CamelModel
from routes.deps import OPERATOR_ID
from services.scheduler import compute_next_run
from tools.catalog import approval_scopes

router = APIRouter(prefix="/tasks", tags=["tasks"])

_TASK_KINDS = frozenset(k.value for k in TaskKind)
_TASK_OUTPUTS = frozenset(o.value for o in TaskOutput)
_SCHEDULE_TYPES = frozenset(t.value for t in ScheduleType)


# --- wire shapes -----------------------------------------------------------------


class TaskSchedule(CamelModel):
    """One task's trigger — exactly one of ``run_at``/``every_seconds``/``cron`` is
    meaningful, selected by ``type``; a ``webhook`` schedule uses none of them."""

    type: str
    run_at: datetime | None = None
    every_seconds: float | None = None
    cron: str | None = None


class TaskCreate(CamelModel):
    kind: str
    title: str
    prompt: str
    schedule: TaskSchedule
    output: str
    pre_authorized: list[str] = []
    enabled: bool = True


class TaskPatch(CamelModel):
    """Partial update — an omitted field is left unchanged. ``rotate_webhook_token``
    is a one-shot action (regenerate the credential), not a stored field."""

    title: str | None = None
    prompt: str | None = None
    schedule: TaskSchedule | None = None
    output: str | None = None
    pre_authorized: list[str] | None = None
    enabled: bool | None = None
    rotate_webhook_token: bool = False


class TaskOut(CamelModel):
    id: str
    kind: str
    title: str
    prompt: str
    schedule: TaskSchedule
    output: str
    pre_authorized: list[str]
    enabled: bool
    created_at: datetime
    updated_at: datetime
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    # The relative webhook path (the frontend composes the absolute URL) — set only
    # for a webhook-type task.
    webhook_url: str | None = None


class TaskListOut(CamelModel):
    items: list[TaskOut]


class TaskRunOut(CamelModel):
    id: str
    task_id: str
    run_id: str | None = None
    conversation_id: str | None = None
    started_at: datetime
    finished_at: datetime | None = None
    outcome: str | None = None
    summary: str | None = None


class TaskRunListOut(CamelModel):
    items: list[TaskRunOut]


class RunNowOut(CamelModel):
    task_run_id: str


# --- validation --------------------------------------------------------------------


def _validate_schedule(schedule: TaskSchedule) -> None:
    if schedule.type not in _SCHEDULE_TYPES:
        raise HTTPException(status_code=422, detail=f"unknown schedule type {schedule.type!r}")
    if schedule.type == ScheduleType.ONCE.value and schedule.run_at is None:
        raise HTTPException(
            status_code=422, detail="schedule.runAt is required for a 'once' schedule"
        )
    if schedule.type == ScheduleType.INTERVAL.value and (
        schedule.every_seconds is None or schedule.every_seconds <= 0
    ):
        raise HTTPException(
            status_code=422,
            detail="schedule.everySeconds must be a positive number for an 'interval' schedule",
        )
    if schedule.type == ScheduleType.CRON.value:
        if not schedule.cron:
            raise HTTPException(
                status_code=422, detail="schedule.cron is required for a 'cron' schedule"
            )
        try:
            croniter(schedule.cron)
        except (ValueError, KeyError) as exc:
            raise HTTPException(
                status_code=422, detail=f"invalid cron expression: {exc}"
            ) from exc


async def _validate_pre_authorized(request: Request, values: list[str]) -> None:
    """A task may only pre-authorize (`AE-3.5`) a tool that can actually pause a run —
    the same vocabulary `ApprovalGrant.tool_name` uses, so a task's standing scope and a
    conversation grant name the same things.

    Derived from the live catalog rather than a constant here, because the operator's
    external tools are named from their own registered servers and connectors and so are
    only knowable at runtime (`tools/catalog.py::approval_scopes`). A stored scope that
    stops existing — a server the operator removed — simply stops matching anything at
    run time; it is rejected only on write, so an unrelated edit to an old task doesn't
    fail because of a source that has since gone.
    """
    known = {
        s.name
        for s in await approval_scopes(
            deps.external(request),
            OPERATOR_ID,
            deps.tool_categories(request),
            deps.gated_tools(request),
        )
    }
    unknown = [v for v in values if v not in known]
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"unknown pre-authorization scope(s): {', '.join(sorted(unknown))}",
        )


def _next_run_for(schedule: TaskSchedule, *, anchor: datetime) -> datetime | None:
    if schedule.type == ScheduleType.WEBHOOK.value:
        return None
    return compute_next_run(
        schedule.type,
        anchor=anchor,
        run_at=schedule.run_at,
        every_seconds=schedule.every_seconds,
        cron_expr=schedule.cron,
    )


# --- read/write helpers --------------------------------------------------------------


def _task_out(task: ScheduledTask, vault: Vault) -> TaskOut:
    is_webhook = task.schedule_type == ScheduleType.WEBHOOK.value
    return TaskOut(
        id=task.id,
        kind=task.kind,
        title=vault.decrypt_str(task.title_enc),
        prompt=vault.decrypt_str(task.prompt_enc),
        schedule=TaskSchedule(
            type=task.schedule_type,
            run_at=task.run_at,
            every_seconds=task.every_seconds,
            cron=task.cron_expr,
        ),
        output=task.output,
        pre_authorized=list(task.pre_authorized),
        enabled=task.enabled,
        created_at=task.created_at,
        updated_at=task.updated_at,
        last_run_at=task.last_run_at,
        next_run_at=task.next_run_at,
        webhook_url=(
            f"/tasks/hooks/{task.webhook_token}" if is_webhook and task.webhook_token else None
        ),
    )


def _task_run_out(run: TaskRun, vault: Vault) -> TaskRunOut:
    return TaskRunOut(
        id=run.id,
        task_id=run.task_id,
        run_id=run.run_id,
        conversation_id=run.conversation_id,
        started_at=run.started_at,
        finished_at=run.finished_at,
        outcome=run.outcome,
        summary=vault.decrypt_str(run.summary_enc) if run.summary_enc is not None else None,
    )


async def _get_owned_task(engine, owner_id: str, task_id: str) -> ScheduledTask | None:
    def work(session: Session) -> ScheduledTask | None:
        row = session.get(ScheduledTask, task_id)
        if row is None or row.owner_id != owner_id:
            return None
        return row

    return await in_session(engine, work)


# --- routes --------------------------------------------------------------------------


@router.get("", response_model=TaskListOut)
async def list_tasks(request: Request) -> TaskListOut:
    engine = deps.db_engine(request)
    vault = deps.vault(request)

    def work(session: Session) -> list[ScheduledTask]:
        return list(
            session.exec(
                select(ScheduledTask)
                .where(ScheduledTask.owner_id == OPERATOR_ID)
                .order_by(ScheduledTask.created_at)
            ).all()
        )

    rows = await in_session(engine, work)
    return TaskListOut(items=[_task_out(row, vault) for row in rows])


@router.post("", status_code=201, response_model=TaskOut)
async def create_task(body: TaskCreate, request: Request) -> TaskOut:
    if body.kind not in _TASK_KINDS:
        raise HTTPException(status_code=422, detail=f"unknown kind {body.kind!r}")
    if body.output not in _TASK_OUTPUTS:
        raise HTTPException(status_code=422, detail=f"unknown output {body.output!r}")
    if not body.title.strip():
        raise HTTPException(status_code=422, detail="title must not be empty")
    if not body.prompt.strip():
        raise HTTPException(status_code=422, detail="prompt must not be empty")
    _validate_schedule(body.schedule)
    await _validate_pre_authorized(request, body.pre_authorized)

    engine = deps.db_engine(request)
    vault = deps.vault(request)
    is_webhook = body.schedule.type == ScheduleType.WEBHOOK.value
    task = ScheduledTask(
        owner_id=OPERATOR_ID,
        kind=body.kind,
        title_enc=vault.encrypt_str(body.title),
        prompt_enc=vault.encrypt_str(body.prompt),
        schedule_type=body.schedule.type,
        run_at=body.schedule.run_at,
        every_seconds=body.schedule.every_seconds,
        cron_expr=body.schedule.cron,
        output=body.output,
        pre_authorized=list(body.pre_authorized),
        enabled=body.enabled,
        webhook_token=new_webhook_token() if is_webhook else None,
        next_run_at=_next_run_for(body.schedule, anchor=utcnow()),
    )

    def work(session: Session) -> ScheduledTask:
        session.add(task)
        session.flush()
        session.refresh(task)
        return task

    saved = await in_session(engine, work)
    deps.scheduler(request).wake()
    return _task_out(saved, vault)


@router.patch("/{task_id}", response_model=TaskOut)
async def update_task(task_id: str, body: TaskPatch, request: Request) -> TaskOut:
    engine = deps.db_engine(request)
    vault = deps.vault(request)
    existing = await _get_owned_task(engine, OPERATOR_ID, task_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="task not found")

    if body.output is not None and body.output not in _TASK_OUTPUTS:
        raise HTTPException(status_code=422, detail=f"unknown output {body.output!r}")
    if body.title is not None and not body.title.strip():
        raise HTTPException(status_code=422, detail="title must not be empty")
    if body.prompt is not None and not body.prompt.strip():
        raise HTTPException(status_code=422, detail="prompt must not be empty")
    if body.schedule is not None:
        _validate_schedule(body.schedule)
    if body.pre_authorized is not None:
        await _validate_pre_authorized(request, body.pre_authorized)
    effective_schedule_type = (
        body.schedule.type if body.schedule is not None else existing.schedule_type
    )
    if body.rotate_webhook_token and effective_schedule_type != ScheduleType.WEBHOOK.value:
        raise HTTPException(
            status_code=422, detail="rotateWebhookToken only applies to a webhook-type task"
        )

    def work(session: Session) -> ScheduledTask | None:
        row = session.get(ScheduledTask, task_id)
        if row is None or row.owner_id != OPERATOR_ID:
            return None
        if body.title is not None:
            row.title_enc = vault.encrypt_str(body.title)
        if body.prompt is not None:
            row.prompt_enc = vault.encrypt_str(body.prompt)
        if body.output is not None:
            row.output = body.output
        if body.pre_authorized is not None:
            row.pre_authorized = list(body.pre_authorized)
        if body.enabled is not None:
            row.enabled = body.enabled
        if body.schedule is not None:
            is_webhook = body.schedule.type == ScheduleType.WEBHOOK.value
            row.schedule_type = body.schedule.type
            row.run_at = body.schedule.run_at
            row.every_seconds = body.schedule.every_seconds
            row.cron_expr = body.schedule.cron
            if is_webhook:
                row.next_run_at = None
                if row.webhook_token is None:
                    row.webhook_token = new_webhook_token()
            else:
                row.webhook_token = None
                row.next_run_at = _next_run_for(body.schedule, anchor=utcnow())
        if body.rotate_webhook_token:
            row.webhook_token = new_webhook_token()
        row.updated_at = utcnow()
        session.add(row)
        session.flush()
        session.refresh(row)
        return row

    saved = await in_session(engine, work)
    if saved is None:
        raise HTTPException(status_code=404, detail="task not found")
    deps.scheduler(request).wake()
    return _task_out(saved, vault)


@router.delete("/{task_id}", status_code=204)
async def delete_task(task_id: str, request: Request) -> None:
    engine = deps.db_engine(request)
    existing = await _get_owned_task(engine, OPERATOR_ID, task_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="task not found")

    def work(session: Session) -> None:
        row = session.get(ScheduledTask, task_id)
        if row is not None:
            session.delete(row)  # ON DELETE CASCADE drops its task_runs too

    await in_session(engine, work)


@router.post("/{task_id}/run_now", status_code=202, response_model=RunNowOut)
async def run_now(task_id: str, request: Request) -> RunNowOut:
    """Fire the task immediately, through the scheduler's own non-overlap path — a
    still-live previous execution records a ``skipped`` `TaskRun` rather than running
    twice."""
    engine = deps.db_engine(request)
    existing = await _get_owned_task(engine, OPERATOR_ID, task_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="task not found")
    if not existing.enabled:
        # A distinct, clearer error than the generic "not found" below — the task
        # exists, it's just been told not to run; re-enable it before firing.
        raise HTTPException(status_code=409, detail="task is disabled")
    task_run_id = await deps.scheduler(request).fire_now(task_id)
    if task_run_id is None:  # raced delete (or a concurrent disable) between the
        # ownership check above and the fire itself
        raise HTTPException(status_code=404, detail="task not found")
    return RunNowOut(task_run_id=task_run_id)


@router.get("/{task_id}/runs", response_model=TaskRunListOut)
async def list_task_runs(
    task_id: str, request: Request, limit: int = Query(default=50, ge=1, le=200)
) -> TaskRunListOut:
    engine = deps.db_engine(request)
    vault = deps.vault(request)
    existing = await _get_owned_task(engine, OPERATOR_ID, task_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="task not found")

    def work(session: Session) -> list[TaskRun]:
        return list(
            session.exec(
                select(TaskRun)
                .where(TaskRun.task_id == task_id)
                .order_by(TaskRun.started_at.desc())
                .limit(limit)
            ).all()
        )

    rows = await in_session(engine, work)
    return TaskRunListOut(items=[_task_run_out(row, vault) for row in rows])


@router.post("/hooks/{token}", status_code=202)
async def fire_webhook(token: str, request: Request) -> None:
    """Auth-exempt (see `core/auth.py`): the unguessable ``token`` in the path is the
    credential. Fires the matched task the same way ``run_now`` does; 404s (rather
    than 401/403) on an unknown token, so a prober can't distinguish "wrong token"
    from "no such route"."""
    engine = deps.db_engine(request)

    def work(session: Session) -> list[ScheduledTask]:
        return list(
            session.exec(
                select(ScheduledTask).where(
                    ScheduledTask.schedule_type == ScheduleType.WEBHOOK.value
                )
            ).all()
        )

    candidates = await in_session(engine, work)
    matched = next(
        (
            candidate
            for candidate in candidates
            if candidate.webhook_token is not None
            and secrets.compare_digest(candidate.webhook_token, token)
        ),
        None,
    )
    if matched is None:
        raise HTTPException(status_code=404, detail="not found")
    await deps.scheduler(request).fire_now(matched.id)
