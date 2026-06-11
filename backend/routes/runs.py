"""Substrate HTTP surface: observe, stream, and cancel a Run.

These are the transport-level endpoints every orchestrator inherits. Creating a
Run is a feature concern (chat/agent/research routes), not here — those call
``request.app.state.runs.submit(...)`` and hand the client back the run id.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from pydantic_ai import ToolApproved, ToolDenied

from agent import ParkedTurn, build_resume_orchestrator
from routes import deps
from runs import Run, RunStatus, parse_last_event_id, sse_response
from tools import Capabilities

router = APIRouter(prefix="/runs", tags=["runs"])


class RunView(BaseModel):
    id: str
    kind: str
    status: str
    owner_id: str
    detail: str | None = None
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    last_seq: int


def _view(run: Run) -> RunView:
    return RunView(
        id=run.id,
        kind=run.kind,
        status=run.status.value,
        owner_id=run.owner_id,
        detail=run.detail,
        error=run.error,
        created_at=run.created_at,
        started_at=run.started_at,
        ended_at=run.ended_at,
        last_seq=run.stream.last_seq,
    )


def _require_run(request: Request, run_id: str) -> Run:
    run = deps.registry(request).get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run


@router.get("/{run_id}", response_model=RunView)
async def get_run(run_id: str, request: Request) -> RunView:
    return _view(_require_run(request, run_id))


@router.get("/{run_id}/events")
async def stream_run_events(
    run_id: str,
    request: Request,
    last_event_id: int | None = Query(default=None),
):
    """SSE event stream. Reconnect with ``Last-Event-ID`` to replay missed events."""
    run = _require_run(request, run_id)
    after = parse_last_event_id(request.headers.get("last-event-id"), last_event_id)
    return sse_response(run, after)


@router.post("/{run_id}/cancel", status_code=202)
async def cancel_run(run_id: str, request: Request) -> dict[str, str]:
    registry = deps.registry(request)
    cancelled = await registry.cancel(run_id)
    if not cancelled:
        # Unknown, or already terminal — surface the distinction.
        run = registry.get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        raise HTTPException(status_code=409, detail=f"run already {run.status.value}")
    return {"status": "cancelling"}


class ApprovalDecision(BaseModel):
    tool_call_id: str
    approved: bool
    message: str | None = None  # shown to the model on denial
    override_args: dict[str, Any] | None = None  # replace args on approval


class ApprovalDecisions(BaseModel):
    decisions: list[ApprovalDecision]


@router.post("/{run_id}/approve", status_code=202)
async def approve_run(run_id: str, body: ApprovalDecisions, request: Request) -> dict[str, str]:
    """Decide the sensitive actions a parked run is awaiting, then resume it."""
    registry = deps.registry(request)
    run = registry.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if run.status is not RunStatus.awaiting_input or not isinstance(run.parked_payload, ParkedTurn):
        raise HTTPException(status_code=409, detail=f"run is not awaiting approval ({run.status})")

    parked: ParkedTurn = run.parked_payload
    pending = {call.tool_call_id for call in parked.requests.approvals}
    provided = {d.tool_call_id for d in body.decisions}
    if provided != pending:
        raise HTTPException(
            status_code=400,
            detail=f"decisions must cover exactly the pending calls: {sorted(pending)}",
        )

    decisions: dict[str, ToolApproved | ToolDenied] = {}
    for decision in body.decisions:
        if decision.approved:
            decisions[decision.tool_call_id] = ToolApproved(override_args=decision.override_args)
        else:
            decisions[decision.tool_call_id] = ToolDenied(
                message=decision.message or "The operator denied this action."
            )

    orchestrator = build_resume_orchestrator(
        parked,
        decisions,
        capabilities=Capabilities(
            memory=deps.memory(request),
            sandbox_sessions=deps.sandbox_sessions(request),
            artifacts=deps.artifacts(request),
        ),
        store=deps.store(request),
    )
    if await registry.resume(run_id, orchestrator) is None:
        raise HTTPException(status_code=409, detail="run could not be resumed")
    return {"status": "resuming"}
