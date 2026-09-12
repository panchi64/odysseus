"""The sub-agents a thread has launched — what the panel draws its cards from.

One read, and deliberately only one. Everything else a card needs is already a route:
a sub-agent's transcript is ``GET /conversations/{child_id}/messages`` because a sub-agent
*is* a conversation, its live tail is ``GET /runs/{run_id}/events`` because it is a run,
its approval is ``POST /runs/{run_id}/approve``, and stopping it is
``POST /runs/{run_id}/cancel``. Adding sub-agent-shaped copies of any of those would be a
second surface over the same objects, and the second one is the one that goes stale.

**Why a list rather than a feed.** The obvious shape is a stream — but the thing being
watched outlives every stream there is to hang it on. A sub-agent's own run stream ends
when *it* does, and the launching thread's ends when its turn does, which is usually long
before. A feed would therefore have to be a third stream that fans the others in, kept per
conversation for as long as anyone might look, holding subscriptions to runs nobody is
reading. This list, re-read while anything is live, is the same information without that
machine — and it is also the only shape that survives a restart, which is precisely when
the operator most wants to know what happened.

Mounted under ``/conversations`` rather than at a surface of its own, because that is what
this is: a property of a thread, reached with the same grant that reads the thread.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from routes.deps import OPERATOR_ID
from services.subagents import SubagentLauncher, SubagentView

router = APIRouter(prefix="/conversations", tags=["subagents"])


class Subagent(BaseModel):
    """One card. Named for what the operator sees rather than for the row behind it."""

    id: str
    #: The sub-agent's own thread, which is where its transcript is read from.
    conversation_id: str
    #: Its run — live tail, approvals, and cancelling, all of which are run routes.
    run_id: str
    name: str
    task: str
    #: ``running`` | ``blocked`` | ``done`` | ``failed`` | ``cancelled``. The first two are
    #: live; a blocked one is waiting on the operator rather than on the machine.
    status: str
    #: What it reported, once it has. While it is still going this is its latest answer
    #: instead — a current best, explicitly not a report.
    summary: str | None = None
    error: str | None = None
    #: How full its context window is. Both are null until its run has made a request, and
    #: a finished sub-agent keeps the last figures it had.
    context_used: int | None = None
    context_window: int | None = None
    started_at: datetime
    ended_at: datetime | None = None


class SubagentList(BaseModel):
    subagents: list[Subagent]


def _card(view: SubagentView) -> Subagent:
    return Subagent(
        id=view.subagent_id,
        conversation_id=view.conversation_id,
        run_id=view.run_id,
        name=view.name,
        task=view.task,
        status=view.status,
        summary=view.summary,
        error=view.error,
        context_used=view.context_used,
        context_window=view.context_window,
        started_at=view.started_at,
        ended_at=view.ended_at,
    )


@router.get("/{conversation_id}/subagents", response_model=SubagentList)
async def list_subagents(conversation_id: str, request: Request) -> SubagentList:
    """Every sub-agent this thread has launched, newest first — live ones and finished.

    Finished ones are kept for the whole life of the thread rather than dropped once their
    report has landed: the operator's reason for looking is usually that something went
    wrong, and that is exactly the case where the card has already stopped being live.
    """
    launcher = request.app.state.capabilities.get_optional(SubagentLauncher)
    if launcher is None:
        raise HTTPException(status_code=404, detail="sub-agents are not available")
    views = await launcher.for_parent(OPERATOR_ID, conversation_id)
    return SubagentList(subagents=[_card(view) for view in views])
