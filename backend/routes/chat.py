"""Chat — create a Run that drives the agent over a prompt.

This is a *feature* route: it owns Run creation (the substrate doesn't), hands
the client a run id, and the client then streams it from ``/runs/{id}/events``.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from agent import build_chat_orchestrator
from runs import RunRegistry

router = APIRouter(prefix="/chat", tags=["chat"])

# Single operator (D14): every record is attributed to this owner for now.
_OPERATOR = "operator"


class ChatCreate(BaseModel):
    prompt: str
    model: str | None = None  # per-conversation `main` override (D16); future


class ChatCreated(BaseModel):
    run_id: str


def _registry(request: Request) -> RunRegistry:
    return request.app.state.runs


@router.post("", status_code=202, response_model=ChatCreated)
async def create_chat(body: ChatCreate, request: Request) -> ChatCreated:
    orchestrator = build_chat_orchestrator(body.prompt)
    run = _registry(request).submit(
        kind="chat",
        owner_id=_OPERATOR,
        orchestrator=orchestrator,
    )
    return ChatCreated(run_id=run.id)
