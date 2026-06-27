"""Chat — create a Run that drives the agent over a prompt.

This is a *feature* route: it owns Run creation (the substrate doesn't), hands
the client a run id (and the conversation id), and the client then streams it
from ``/runs/{id}/events``. A turn continues its conversation's history and
persists its new messages through the conversation store.

Beyond a fresh turn it also drives the two history-rewriting turns — **regenerate**
(re-answer the last request) and **edit** (re-ask a changed request) — which share
this router because both create a Run. They differ only in how the conversation
store repositions the active leaf first; the launch is identical.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings

from agent import build_chat_orchestrator
from core.config import get_settings
from core.exceptions import DegradedCapabilityError, NotFoundError
from routes import deps
from routes.deps import OPERATOR_ID
from services.settings_store import (
    get_attachment_inline_max_tokens,
    set_attachment_inline_max_tokens,
)
from tools import Capabilities

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatCreate(BaseModel):
    prompt: str
    conversation_id: str | None = None  # continue an existing conversation
    # Per-conversation `main` override from the chat picker: which provider
    # (`endpoint_id`) and which model on it (`model`, discovered from the provider).
    endpoint_id: str | None = None
    model: str | None = None
    # Files the operator attached to this message (existing upload ids — the client
    # uploads first via POST /uploads, then sends the ids here). They're handed to the
    # model for this turn and enrolled in the knowledge base via the upload pipeline.
    attachment_ids: list[str] = []
    # When creating a fresh conversation, mark it a scratch thread the listing
    # hides (the side-by-side compare panes set this). Ignored when continuing an
    # existing conversation.
    ephemeral: bool = False


class RegenerateCreate(BaseModel):
    conversation_id: str
    message_id: str  # the assistant turn to re-answer (its branch node id)
    # Optional per-turn model override — regenerate with a different provider/model.
    endpoint_id: str | None = None
    model: str | None = None


class EditCreate(BaseModel):
    conversation_id: str
    message_id: str  # the user turn to replace (its request node id)
    prompt: str  # the edited message
    endpoint_id: str | None = None
    model: str | None = None
    # Attachments for the edited turn — a fresh user request, so the same direct-inject
    # path as a new message (regenerate, which adds no new request, takes none).
    attachment_ids: list[str] = []


class ChatCreated(BaseModel):
    run_id: str
    conversation_id: str


class ChatSettings(BaseModel):
    """Operator-tunable chat preferences. ``attachment_inline_max_tokens`` is the token
    budget an attached file's text is retained inline for before it's cut off with a tool
    pointer (images are always retained, regardless). camelCase out to match the frontend."""

    model_config = ConfigDict(populate_by_name=True)

    attachment_inline_max_tokens: int = Field(ge=0, alias="attachmentInlineMaxTokens")


async def _resolve_models(
    request: Request, endpoint_id: str | None, model: str | None
) -> tuple[Model, Model, ModelSettings | None, int | None, bool]:
    """Resolve the `main` model plus the background (utility/title) pair, raising a
    clear 4xx/503 on misconfiguration.

    Kept separate from the submit step so it runs **before** any conversation
    mutation: a regenerate/edit must not reposition (and persist) the active leaf
    only to fail here, which would leave the thread truncated with no replacement."""
    # Resolve the `main` model now (per-conversation endpoint override included),
    # so a model misconfiguration surfaces as a clear 4xx/503 rather than a run
    # that starts and immediately errors.
    registry = deps.models(request)
    try:
        main = await registry.resolve_detailed(
            "main",
            owner_id=OPERATOR_ID,
            override_endpoint_id=endpoint_id,
            override_model=model,
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="model endpoint not found") from None
    except DegradedCapabilityError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    resolved = main.model

    # Background work — verification (opt-in) and auto-titling (on by default) —
    # runs on the cheap `utility` model, with the title call wanting its
    # reasoning-off settings too (a fast, no-thinking pass). Resolve the pair only
    # when a background feature is enabled, so a plain chat with both off pays
    # nothing; when no `utility` endpoint is bound, reuse the resolved `main` model
    # (picker override included) so both work without extra setup.
    settings = get_settings()
    utility_model = resolved
    title_settings: ModelSettings | None = None
    if settings.verify_enabled or settings.title_enabled:
        background = await registry.resolve_background(
            owner_id=OPERATOR_ID,
            override_endpoint_id=endpoint_id,
            override_model=model,
        )
        utility_model = background.model
        title_settings = background.reasoning_off
    return resolved, utility_model, title_settings, main.context_window, main.vision


def _submit_turn(
    request: Request,
    *,
    prompt: str | None,
    conversation_id: str,
    models: tuple[Model, Model, ModelSettings | None, int | None, bool],
    attachment_ids: list[str] | None = None,
    ephemeral: bool = False,
    inline_max_tokens: int | None = None,
) -> ChatCreated:
    """Build the chat orchestrator from pre-resolved models and submit the Run.

    No failure path after the caller's conversation mutation — ``prompt is None``
    is a regenerate (re-run from a history that already ends in the user request).
    ``ephemeral`` threads (e.g. the compare panes) are hidden from the listing and
    show no title, so auto-titling them is invisible work that only holds the run
    open after the answer — skip it by passing no title model."""
    resolved, utility_model, background_settings, context_window, vision = models
    orchestrator = build_chat_orchestrator(
        prompt,
        model=resolved,
        utility_model=utility_model,
        utility_settings=background_settings,
        title_model=None if ephemeral else utility_model,
        title_settings=None if ephemeral else background_settings,
        context_window=context_window,
        capabilities=Capabilities(
            memory=deps.memory(request),
            sandbox_sessions=deps.sandbox_sessions(request),
            artifacts=deps.artifacts(request),
            search=deps.search(request),
            fetcher=deps.fetcher(request),
            conversation_search=deps.conversation_search(request),
            corpus=deps.corpus(request),
            uploads=deps.uploads(request),
            grants=deps.approval_grants(request),
        ),
        store=deps.store(request),
        conversation_id=conversation_id,
        uploads=deps.uploads(request),
        attachment_ids=attachment_ids,
        vision=vision,
        inline_max_tokens=inline_max_tokens,
    )
    run = deps.registry(request).submit(
        kind="chat",
        owner_id=OPERATOR_ID,
        orchestrator=orchestrator,
        conversation_id=conversation_id,
    )
    return ChatCreated(run_id=run.id, conversation_id=conversation_id)


async def _validate_attachments(request: Request, attachment_ids: list[str]) -> None:
    """Every attached id must name an upload the operator owns — reject foreign/unknown
    ids with a clear 404 rather than silently dropping them at run time."""
    if not attachment_ids:
        return
    uploads = deps.uploads(request)
    for upload_id in attachment_ids:
        # Cheap ownership check — decrypts nothing (resolve_attachments opens the bytes/text
        # later, only for ids that survive to run time).
        if not await uploads.owns(OPERATOR_ID, upload_id):
            raise HTTPException(
                status_code=404, detail=f"attachment {upload_id!r} not found"
            )


async def _attachment_inline_cap(
    request: Request, attachment_ids: list[str]
) -> int | None:
    """The operator's inline-retention token cap, read only for a turn that actually
    carries attachments (a plain chat turn skips the lookup). ``None`` ⇒ no attachments,
    so the orchestrator never consults it."""
    if not attachment_ids:
        return None
    return await get_attachment_inline_max_tokens(deps.settings_store(request), OPERATOR_ID)


@router.post("", status_code=202, response_model=ChatCreated)
async def create_chat(body: ChatCreate, request: Request) -> ChatCreated:
    # A turn needs *something* to act on: text, or at least one attached file ("here,
    # look at this").
    if not body.prompt.strip() and not body.attachment_ids:
        raise HTTPException(status_code=422, detail="prompt must not be empty")
    await _validate_attachments(request, body.attachment_ids)

    # Resolve before creating/continuing — a model failure shouldn't leave an
    # empty orphan conversation behind.
    models = await _resolve_models(request, body.endpoint_id, body.model)

    store = deps.store(request)
    if body.conversation_id is not None:
        # Continue an existing conversation, but only one the operator owns —
        # an unknown id must not silently spawn orphan messages.
        if not await store.exists(body.conversation_id, OPERATOR_ID):
            raise HTTPException(status_code=404, detail="conversation not found")
        conversation_id = body.conversation_id
    else:
        conversation_id = await store.create_conversation(
            OPERATOR_ID, ephemeral=body.ephemeral
        )

    cap = await _attachment_inline_cap(request, body.attachment_ids)
    return _submit_turn(
        request,
        prompt=body.prompt,
        conversation_id=conversation_id,
        models=models,
        attachment_ids=body.attachment_ids,
        ephemeral=body.ephemeral,
        inline_max_tokens=cap,
    )


@router.post("/regenerate", status_code=202, response_model=ChatCreated)
async def regenerate(body: RegenerateCreate, request: Request) -> ChatCreated:
    """Re-answer a turn: drop back to the user request that produced ``message_id``
    and run again (no new prompt), recording the answer as a new version alongside
    the old one. An optional model override regenerates with a different model."""
    store = deps.store(request)
    if not await store.exists(body.conversation_id, OPERATOR_ID):
        raise HTTPException(status_code=404, detail="conversation not found")
    # Resolve before repositioning the active leaf: a failed resolve must not
    # leave the thread branched back with no new answer to replace the old one.
    models = await _resolve_models(request, body.endpoint_id, body.model)
    if not await store.regenerate_point(body.conversation_id, body.message_id):
        raise HTTPException(status_code=404, detail="message not found")
    return _submit_turn(
        request, prompt=None, conversation_id=body.conversation_id, models=models
    )


@router.post("/edit", status_code=202, response_model=ChatCreated)
async def edit(body: EditCreate, request: Request) -> ChatCreated:
    """Re-ask a changed request: branch from the edited user turn's parent and run
    with the new prompt, recording a new version of that turn (and a fresh answer)
    beside the original."""
    if not body.prompt.strip() and not body.attachment_ids:
        raise HTTPException(status_code=422, detail="prompt must not be empty")
    await _validate_attachments(request, body.attachment_ids)
    store = deps.store(request)
    if not await store.exists(body.conversation_id, OPERATOR_ID):
        raise HTTPException(status_code=404, detail="conversation not found")
    models = await _resolve_models(request, body.endpoint_id, body.model)
    if not await store.edit_point(body.conversation_id, body.message_id):
        raise HTTPException(status_code=404, detail="message not found")
    cap = await _attachment_inline_cap(request, body.attachment_ids)
    return _submit_turn(
        request,
        prompt=body.prompt,
        conversation_id=body.conversation_id,
        models=models,
        attachment_ids=body.attachment_ids,
        inline_max_tokens=cap,
    )


@router.get("/settings", response_model=ChatSettings)
async def get_chat_settings(request: Request) -> ChatSettings:
    """The operator's chat preferences (the runtime override, else the config default)."""
    value = await get_attachment_inline_max_tokens(deps.settings_store(request), OPERATOR_ID)
    return ChatSettings(attachment_inline_max_tokens=value)


@router.put("/settings", response_model=ChatSettings)
async def update_chat_settings(body: ChatSettings, request: Request) -> ChatSettings:
    """Set the chat attachment inline token cap (a non-negative int; ``ge=0`` is enforced
    on the body, so a bad value is rejected before it reaches the store)."""
    stored = await set_attachment_inline_max_tokens(
        deps.settings_store(request), OPERATOR_ID, body.attachment_inline_max_tokens
    )
    return ChatSettings(attachment_inline_max_tokens=stored)
