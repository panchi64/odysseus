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
from core.config import get_settings
from core.exceptions import DegradedCapabilityError, NotFoundError
from routes import deps
from routes.deps import OPERATOR_ID
from tools import Capabilities

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatCreate(BaseModel):
    prompt: str
    conversation_id: str | None = None  # continue an existing conversation
    # Per-conversation `main` override from the chat picker: which provider
    # (`endpoint_id`) and which model on it (`model`, discovered from the provider).
    endpoint_id: str | None = None
    model: str | None = None


class ChatCreated(BaseModel):
    run_id: str
    conversation_id: str


@router.post("", status_code=202, response_model=ChatCreated)
async def create_chat(body: ChatCreate, request: Request) -> ChatCreated:
    if not body.prompt.strip():
        raise HTTPException(status_code=422, detail="prompt must not be empty")

    # Resolve the `main` model now (per-conversation endpoint override included),
    # so a model misconfiguration surfaces as a clear 4xx/503 rather than a run
    # that starts and immediately errors.
    registry = deps.models(request)
    try:
        model = await registry.resolve(
            "main",
            owner_id=OPERATOR_ID,
            override_endpoint_id=body.endpoint_id,
            override_model=body.model,
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="model endpoint not found") from None
    except DegradedCapabilityError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    # Background work — verification (opt-in) and auto-titling (on by default) —
    # runs on the cheap `utility` model, with the title call wanting its
    # reasoning-off settings too (a fast, no-thinking pass). Resolve the pair only
    # when a background feature is enabled, so a plain chat with both off pays
    # nothing; when no `utility` endpoint is bound, reuse the resolved `main` model
    # (picker override included) so both work without extra setup.
    settings = get_settings()
    utility_model = model
    title_settings = None
    if settings.verify_enabled or settings.title_enabled:
        try:
            background = await registry.resolve_detailed("utility", owner_id=OPERATOR_ID)
        except (DegradedCapabilityError, NotFoundError):
            background = await registry.resolve_detailed(
                "main",
                owner_id=OPERATOR_ID,
                override_endpoint_id=body.endpoint_id,
                override_model=body.model,
            )
        utility_model = background.model
        title_settings = background.reasoning_off

    store = deps.store(request)
    if body.conversation_id is not None:
        # Continue an existing conversation, but only one the operator owns —
        # an unknown id must not silently spawn orphan messages.
        if not await store.exists(body.conversation_id, OPERATOR_ID):
            raise HTTPException(status_code=404, detail="conversation not found")
        conversation_id = body.conversation_id
    else:
        conversation_id = await store.create_conversation(OPERATOR_ID)

    orchestrator = build_chat_orchestrator(
        body.prompt,
        model=model,
        utility_model=utility_model,
        title_model=utility_model,
        title_settings=title_settings,
        capabilities=Capabilities(
            memory=deps.memory(request),
            sandbox_sessions=deps.sandbox_sessions(request),
            artifacts=deps.artifacts(request),
        ),
        store=store,
        conversation_id=conversation_id,
    )
    run = deps.registry(request).submit(
        kind="chat", owner_id=OPERATOR_ID, orchestrator=orchestrator
    )
    return ChatCreated(run_id=run.id, conversation_id=conversation_id)
