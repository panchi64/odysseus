"""Substrate HTTP surface: observe, stream, and cancel a Run.

These are the transport-level endpoints every orchestrator inherits. Creating a
Run is a feature concern (chat/agent/research routes), not here — those call
``request.app.state.runs.submit(...)`` and hand the client back the run id.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import ToolApproved, ToolDenied

from agent import ParkedTurn, build_resume_orchestrator
from routes import deps
from runs import Run, RunStatus, parse_last_event_id, sse_response
from services.approval_grants import covered_by_grant

router = APIRouter(prefix="/runs", tags=["runs"])


class RunView(BaseModel):
    # Existing fields stay snake_case (this surface predates the camelCase
    # convention); the two new dashboard fields below are camelCase to match the
    # newer surfaces (documents/gallery/corpus/notifications) — `populate_by_name`
    # lets this model still build from the plain attribute names below.
    model_config = ConfigDict(populate_by_name=True)

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
    # The conversation this run drives, and its (possibly not-yet-titled) name — lets
    # the dashboard label + link an in-flight run without a second lookup. `status`
    # above already carries queued/running/awaiting_input for the active listing.
    conversation_id: str | None = Field(default=None, alias="conversationId")
    conversation_title: str | None = Field(default=None, alias="conversationTitle")


def _view(run: Run, title: str | None) -> RunView:
    """One run projected for the client. The conversation title is passed in rather than
    looked up here: the listing resolves every run's title in a single query, and a helper
    that reached for the store itself would put that back to one read per run."""
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
        conversation_id=run.conversation_id,
        conversation_title=title,
    )


def _require_run(request: Request, run_id: str) -> Run:
    run = deps.registry(request).get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run


@router.get("", response_model=list[RunView])
async def list_runs(request: Request, active: bool = Query(default=True)) -> list[RunView]:
    """The operator's runs, newest first. ``active=True`` (default) returns only
    the ones still in flight (not yet terminal) — what the home page surfaces."""
    runs = deps.registry(request).list(deps.OPERATOR_ID)
    if active:
        runs = [r for r in runs if not r.is_terminal]
    runs.sort(key=lambda r: r.created_at, reverse=True)
    titles = await deps.store(request).titles(
        [r.conversation_id for r in runs if r.conversation_id is not None],
        deps.OPERATOR_ID,
    )
    return [
        _view(r, titles.get(r.conversation_id) if r.conversation_id else None)
        for r in runs
    ]


@router.get("/{run_id}", response_model=RunView)
async def get_run(run_id: str, request: Request) -> RunView:
    run = _require_run(request, run_id)
    titles = (
        await deps.store(request).titles([run.conversation_id], run.owner_id)
        if run.conversation_id is not None
        else {}
    )
    return _view(run, titles.get(run.conversation_id or ""))


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


class QueuedMessageEdit(BaseModel):
    text: str


@router.patch("/{run_id}/messages/{message_id}", status_code=200)
async def edit_queued_message(
    run_id: str, message_id: str, body: QueuedMessageEdit, request: Request
) -> dict[str, str]:
    """Rewrite an operator message queued into a live run before the run consumes
    it (the message keeps its id and place in the queue). Same 404 envelope as
    withdraw: unknown id, already injected, already withdrawn, or the run is
    gone/terminal — the message can no longer be edited."""
    if not body.text.strip():
        raise HTTPException(status_code=422, detail="text must not be empty")
    run = _require_run(request, run_id)
    if run.is_terminal or not run.edit_message(message_id, body.text):
        raise HTTPException(status_code=404, detail="queued message not found")
    return {"status": "edited"}


@router.delete("/{run_id}/messages/{message_id}", status_code=200)
async def withdraw_queued_message(
    run_id: str, message_id: str, request: Request
) -> dict[str, str]:
    """Withdraw an operator message queued into a live run before the run consumes
    it. 404 covers every way the message can no longer be withdrawn: unknown id,
    already injected, already withdrawn, or the run is gone/terminal."""
    run = _require_run(request, run_id)
    if run.is_terminal or not run.withdraw_message(message_id):
        raise HTTPException(status_code=404, detail="queued message not found")
    return {"status": "withdrawn"}


class ApprovalDecision(BaseModel):
    tool_call_id: str
    approved: bool
    message: str | None = None  # shown to the model on denial
    override_args: dict[str, Any] | None = None  # replace args on approval
    # "conversation" records an auto-approval grant for this tool so the same call
    # isn't re-prompted for the rest of the conversation; "once" is this call only.
    scope: Literal["once", "conversation"] = "once"


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
    # The operator only decides the calls that weren't already auto-approved by an
    # active conversation grant; those ride on the parked payload and merge back below.
    tool_by_id = {call.tool_call_id: call.tool_name for call in parked.requests.approvals}
    pending = set(tool_by_id) - set(parked.pre_approved)
    provided = {d.tool_call_id for d in body.decisions}
    if provided != pending:
        raise HTTPException(
            status_code=400,
            detail=f"decisions must cover exactly the pending calls: {sorted(pending)}",
        )

    grants = deps.approval_grants(request)
    # Re-validate the grant-driven pre-approvals against the *current* grants: a grant
    # the operator revoked — or that lapsed by TTL — while the run was parked must not
    # still auto-run its call.
    active = (
        await grants.active(deps.OPERATOR_ID, parked.conversation_id)
        if parked.pre_approved and parked.conversation_id is not None
        else set()
    )
    decisions: dict[str, ToolApproved | ToolDenied] = {}
    for call_id in parked.pre_approved:
        if covered_by_grant(tool_by_id.get(call_id), active):
            decisions[call_id] = ToolApproved()
        else:
            # The grant was revoked or expired while parked; either way it no longer
            # covers the call, so don't assert a cause the transcript can't stand behind.
            decisions[call_id] = ToolDenied(
                message="This tool's conversation auto-approval is no longer in effect."
            )

    # New "allow for this conversation" grants the operator chose this batch. Deduped:
    # two calls to the same tool both opting in map to a single grant.
    to_grant: list[str] = []
    for decision in body.decisions:
        if decision.approved:
            decisions[decision.tool_call_id] = ToolApproved(override_args=decision.override_args)
            if decision.scope == "conversation" and parked.conversation_id is not None:
                tool_name = tool_by_id[decision.tool_call_id]
                if tool_name not in to_grant:
                    to_grant.append(tool_name)
        else:
            decisions[decision.tool_call_id] = ToolDenied(
                message=decision.message or "The operator denied this action."
            )

    # The approval is decided now, one way or another (approved, denied, or already
    # grant-covered) — resolve the park's notification here rather than waiting for the
    # run to reach terminal. Idempotent: a run with no pending approval_needed (or one
    # already resolved) is simply a no-op.
    await deps.notifications(request).resolve_for_run(deps.OPERATOR_ID, run_id)

    orchestrator = build_resume_orchestrator(
        parked,
        decisions,
        # The same app-wide agent-facing bag the original turn ran with — a resumed
        # turn re-runs the approved tool call, and mail-send/vault-read/external are
        # the approval-gated ones, so this resume path is the *only* way they ever run.
        capabilities=deps.capabilities(request),
        store=deps.store(request),
        # A resumed turn respects the operator's disabled set and the current offline
        # state — a tool switched off (or a link dropped) while it was parked stays hidden
        # on resume. This is the only path an approval-gated tool ever actually runs on,
        # so a gate missing here would be a gate that never applies to the calls that
        # matter most.
        # ...and the mode the parked turn ran in, read off the payload rather than the
        # conversation, so the resumed turn is offered the same tools it parked with.
        disabled_tools=await deps.disabled_tools(request, parked.binding.mode),
    )
    # Record grants *before* resuming: resume only schedules the turn (it doesn't await
    # it), and the resumed turn's inline grant check must see them, or a tool re-called
    # within that same turn would re-prompt despite the operator's "allow for this
    # conversation". If the resume can't be accepted, roll the new grants back so a dead
    # run leaves no standing auto-approval behind (these tools had no active grant before,
    # else their calls wouldn't have been pending).
    conv_id = parked.conversation_id
    if to_grant and conv_id is not None:
        for tool_name in to_grant:
            await grants.grant(deps.OPERATOR_ID, conv_id, tool_name)
    if await registry.resume(run_id, orchestrator) is None:
        if to_grant and conv_id is not None:
            for tool_name in to_grant:
                await grants.revoke(deps.OPERATOR_ID, conv_id, tool_name)
        raise HTTPException(status_code=409, detail="run could not be resumed")
    return {"status": "resuming"}
