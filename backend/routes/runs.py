"""Substrate HTTP surface: observe, stream, and cancel a Run.

These are the transport-level endpoints every orchestrator inherits. Creating a
Run is a feature concern (chat/agent/research routes), not here — those call
``request.app.state.runs.submit(...)`` and hand the client back the run id.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from runs import Run, RunRegistry, parse_last_event_id, sse_response

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


def _registry(request: Request) -> RunRegistry:
    return request.app.state.runs


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
    run = _registry(request).get(run_id)
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
    cancelled = await _registry(request).cancel(run_id)
    if not cancelled:
        # Unknown, or already terminal — surface the distinction.
        run = _registry(request).get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        raise HTTPException(status_code=409, detail=f"run already {run.status.value}")
    return {"status": "cancelling"}
