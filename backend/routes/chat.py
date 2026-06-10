"""Chat — create a Run that drives the agent over a prompt.

This is a *feature* route: it owns Run creation (the substrate doesn't), hands
the client a run id (and the conversation id), and the client then streams it
from ``/runs/{id}/events``. A turn continues its conversation's history and
persists its new messages through the conversation store.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from agent import build_chat_orchestrator
from routes import deps

router = APIRouter(prefix="/chat", tags=["chat"])

# Single operator: every record is attributed to this owner for now.
_OPERATOR = "operator"


class ChatCreate(BaseModel):
    prompt: str
    conversation_id: str | None = None  # continue an existing conversation
    model: str | None = None  # per-conversation model override; future


class ChatCreated(BaseModel):
    run_id: str
    conversation_id: str


@router.post("", status_code=202, response_model=ChatCreated)
async def create_chat(body: ChatCreate, request: Request) -> ChatCreated:
    if not body.prompt.strip():
        raise HTTPException(status_code=422, detail="prompt must not be empty")

    store = deps.store(request)
    if body.conversation_id is not None:
        # Continue an existing conversation, but only one the operator owns —
        # an unknown id must not silently spawn orphan messages.
        if not await store.exists(body.conversation_id, _OPERATOR):
            raise HTTPException(status_code=404, detail="conversation not found")
        conversation_id = body.conversation_id
    else:
        conversation_id = await store.create_conversation(_OPERATOR)

    orchestrator = build_chat_orchestrator(
        body.prompt, store=store, conversation_id=conversation_id
    )
    run = deps.registry(request).submit(kind="chat", owner_id=_OPERATOR, orchestrator=orchestrator)
    return ChatCreated(run_id=run.id, conversation_id=conversation_id)
