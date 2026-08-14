"""Chat — create a Run that drives the agent over a prompt.

This is a *feature* route: it owns Run creation (the substrate doesn't), hands
the client a run id (and the conversation id), and the client then streams it
from ``/runs/{id}/events``. A turn continues its conversation's history and
persists its new messages through the conversation store.

Beyond a fresh turn it also drives the two history-rewriting turns — **regenerate**
(re-answer the last request) and **edit** (re-ask a changed request) — which share
this router because both create a Run. They differ only in how the conversation
store repositions the active leaf first; the launch is identical.

``resolve_turn_models``/``compose_turn`` are the two Request-agnostic halves of that
composition (model resolution, then build-the-orchestrator-and-submit), exported so a
non-HTTP caller can drive an ordinary chat turn the same way a route does — the
scheduler's agent-task executor (`app.py`) reuses them rather than forking a second
run-submission path.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings

from agent import build_chat_orchestrator
from agent.compaction import build_compaction_context
from core.config import get_settings
from core.exceptions import DegradedCapabilityError, NotFoundError
from routes import deps
from routes.deps import OPERATOR_ID
from runs import ConversationBusyError, RunRegistry
from services.conversations import ConversationStore
from services.registry import ModelRegistry
from services.settings_store import (
    CompactionSettings,
    get_attachment_inline_max_tokens,
    get_compaction,
    resolve_compaction_enabled,
    set_attachment_inline_max_tokens,
    set_compaction,
)
from services.uploads import UploadStore
from tools import Capabilities, CompactionContext

router = APIRouter(prefix="/chat", tags=["chat"])

_CONVERSATION_BUSY_DETAIL = "A response is already in progress in this conversation"


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
    pointer (images are always retained, regardless). The ``compaction*`` fields tune
    tool-result compaction (digest oversized prior-turn tool outputs for the model). They're
    optional on a PUT — an omitted one is left unchanged — and always populated on a GET.
    snake_case out, matching the rest of the ``/chat`` surface."""

    # `extra="forbid"` so a mistyped/unknown field is a 422, not a silent no-op: with every
    # field optional (omitted ⇒ unchanged), a typo'd key would otherwise be dropped and the PUT
    # would return 200 having changed nothing.
    model_config = ConfigDict(extra="forbid")

    # All fields are optional on a PUT (an omitted one is left unchanged) and always
    # populated on a GET; ``ge=0`` still rejects a negative value when one is provided.
    attachment_inline_max_tokens: int | None = Field(default=None, ge=0)
    compaction_enabled: bool | None = None
    compaction_keep_recent: int | None = Field(default=None, ge=0)
    compaction_min_tokens: int | None = Field(default=None, ge=0)


async def resolve_turn_models(
    model_registry: ModelRegistry,
    endpoint_id: str | None,
    model: str | None,
    *,
    owner_id: str = OPERATOR_ID,
) -> tuple[Model, Model, ModelSettings | None, int | None, bool]:
    """Resolve the `main` model plus the background (utility/title) pair, raising a
    clear 4xx/503 on misconfiguration.

    Kept separate from the submit step so it runs **before** any conversation
    mutation: a regenerate/edit must not reposition (and persist) the active leaf
    only to fail here, which would leave the thread truncated with no replacement."""
    # Resolve the `main` model now (per-conversation endpoint override included),
    # so a model misconfiguration surfaces as a clear 4xx/503 rather than a run
    # that starts and immediately errors.
    try:
        main = await model_registry.resolve_detailed(
            "main",
            owner_id=owner_id,
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
        background = await model_registry.resolve_background(
            owner_id=owner_id,
            override_endpoint_id=endpoint_id,
            override_model=model,
        )
        utility_model = background.model
        title_settings = background.reasoning_off
    return resolved, utility_model, title_settings, main.context_window, main.vision


async def _resolve_models(
    request: Request, endpoint_id: str | None, model: str | None
) -> tuple[Model, Model, ModelSettings | None, int | None, bool]:
    return await resolve_turn_models(deps.models(request), endpoint_id, model)


def compose_turn(
    *,
    prompt: str | None,
    conversation_id: str,
    models: tuple[Model, Model, ModelSettings | None, int | None, bool],
    capabilities: Capabilities,
    registry: RunRegistry,
    store: ConversationStore,
    uploads: UploadStore,
    disabled_tools: frozenset[str] = frozenset(),
    owner_id: str = OPERATOR_ID,
    attachment_ids: list[str] | None = None,
    ephemeral: bool = False,
    inline_max_tokens: int | None = None,
    compaction: CompactionContext | None = None,
) -> ChatCreated:
    """Build the chat orchestrator from pre-resolved models/capabilities and submit
    the Run — the one composition path a live chat turn (`_submit_turn`, resolving
    its resources from the `Request` via `routes.deps`) and an unattended scheduled
    task's execution (`app.py`'s task executor, resolving them straight from
    `app.state`) both fire through, so approval parking, conversation grants, and the
    orchestrator's own wiring can never diverge between the two.

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
        capabilities=capabilities,
        store=store,
        conversation_id=conversation_id,
        uploads=uploads,
        attachment_ids=attachment_ids,
        vision=vision,
        inline_max_tokens=inline_max_tokens,
        compaction=compaction,
        # While offline mode is active the web containers are down, so hide the web
        # tools from the agent rather than let it discover they're unavailable.
        disabled_tools=disabled_tools,
    )
    try:
        run = registry.submit(
            kind="chat",
            owner_id=owner_id,
            orchestrator=orchestrator,
            conversation_id=conversation_id,
        )
    except ConversationBusyError as exc:
        # The registry's own atomic check-and-claim caught a race the caller's
        # earlier `require_conversation_free` guard couldn't (two requests that
        # both saw no active run before either submitted).
        raise HTTPException(status_code=409, detail=_CONVERSATION_BUSY_DETAIL) from exc
    return ChatCreated(run_id=run.id, conversation_id=conversation_id)


async def _submit_turn(
    request: Request,
    *,
    prompt: str | None,
    conversation_id: str,
    models: tuple[Model, Model, ModelSettings | None, int | None, bool],
    attachment_ids: list[str] | None = None,
    ephemeral: bool = False,
    inline_max_tokens: int | None = None,
    compaction: CompactionContext | None = None,
) -> ChatCreated:
    """Gather this route's resources from the `Request` and hand off to `compose_turn`.

    Async only because the enabled-tool policy is a persisted read; every other resource
    here is an `app.state` handle. `compose_turn` itself stays synchronous, so the
    submit remains a single uninterrupted step after the caller's conversation mutation."""
    return compose_turn(
        prompt=prompt,
        conversation_id=conversation_id,
        models=models,
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
            workspace_history=deps.workspace_history(request),
            documents=deps.documents(request),
            skills=deps.skills(request),
            notifications=deps.notifications(request),
            # Reserved sprint capabilities — each accessor reads through `getattr` and
            # returns None until its track hangs the service on `app.state`, so these
            # are wired once here rather than by every track that lands one.
            mail=deps.mail(request),
            calendar=deps.calendar(request),
            secret_vault=deps.secret_vault(request),
            external=deps.external(request),
        ),
        registry=deps.registry(request),
        store=deps.store(request),
        uploads=deps.uploads(request),
        disabled_tools=await deps.disabled_tools(request),
        attachment_ids=attachment_ids,
        ephemeral=ephemeral,
        inline_max_tokens=inline_max_tokens,
        compaction=compaction,
    )


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


async def _resolve_compaction(
    request: Request, conversation_id: str | None
) -> CompactionContext:
    """The effective tool-result compaction context for a turn, with a fresh per-turn handle
    map. Precedence: the conversation's on/off override (if set) beats the operator's global
    default, which beats the config default. Resolved for every turn (a plain turn condenses
    prior tool-heavy turns too)."""
    cs = await get_compaction(deps.settings_store(request), OPERATOR_ID)
    enabled = cs.enabled
    if conversation_id is not None:
        override = await deps.store(request).get_compaction_override(conversation_id)
        enabled = resolve_compaction_enabled(override, cs.enabled)
    return build_compaction_context(
        get_settings(),
        enabled=enabled,
        keep_recent=cs.keep_recent,
        min_tokens=cs.min_tokens,
    )


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

    # Claim now, before the remaining awaits (attachment cap, compaction resolve) and
    # the eventual `submit` below — a plain "is there a live run" check alone leaves a
    # gap a concurrent regenerate/edit/delete could occupy without ever registering a
    # run for `active_run_for` to see. A brand-new conversation's id is unknown to
    # anyone else yet, so this always succeeds for it.
    deps.claim_conversation(request, conversation_id)
    try:
        cap = await _attachment_inline_cap(request, body.attachment_ids)
        return await _submit_turn(
            request,
            prompt=body.prompt,
            conversation_id=conversation_id,
            models=models,
            attachment_ids=body.attachment_ids,
            ephemeral=body.ephemeral,
            inline_max_tokens=cap,
            compaction=await _resolve_compaction(request, conversation_id),
        )
    finally:
        deps.release_conversation(request, conversation_id)


@router.post("/regenerate", status_code=202, response_model=ChatCreated)
async def regenerate(body: RegenerateCreate, request: Request) -> ChatCreated:
    """Re-answer a turn: drop back to the user request that produced ``message_id``
    and run again (no new prompt), recording the answer as a new version alongside
    the old one. An optional model override regenerates with a different model."""
    store = deps.store(request)
    if not await store.exists(body.conversation_id, OPERATOR_ID):
        raise HTTPException(status_code=404, detail="conversation not found")
    # Claim before the model resolve and the leaf-moving `regenerate_point` call —
    # both are real `await`s a second near-simultaneous regenerate/edit could
    # otherwise slip through during: neither request has registered a run yet at
    # that point, so a plain "is there a live run" check can't see the other one
    # coming. Released once this request's own submit/mutation is settled, win or
    # lose (a failed resolve, a 404 message id, or a successful submit).
    deps.claim_conversation(request, body.conversation_id)
    try:
        models = await _resolve_models(request, body.endpoint_id, body.model)
        if not await store.regenerate_point(body.conversation_id, body.message_id):
            raise HTTPException(status_code=404, detail="message not found")
        return await _submit_turn(
            request,
            prompt=None,
            conversation_id=body.conversation_id,
            models=models,
            compaction=await _resolve_compaction(request, body.conversation_id),
        )
    finally:
        deps.release_conversation(request, body.conversation_id)


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
    # Same claim as regenerate — before the model resolve and before the
    # leaf-moving `edit_point` call.
    deps.claim_conversation(request, body.conversation_id)
    try:
        models = await _resolve_models(request, body.endpoint_id, body.model)
        if not await store.edit_point(body.conversation_id, body.message_id):
            raise HTTPException(status_code=404, detail="message not found")
        cap = await _attachment_inline_cap(request, body.attachment_ids)
        return await _submit_turn(
            request,
            prompt=body.prompt,
            conversation_id=body.conversation_id,
            models=models,
            attachment_ids=body.attachment_ids,
            inline_max_tokens=cap,
            compaction=await _resolve_compaction(request, body.conversation_id),
        )
    finally:
        deps.release_conversation(request, body.conversation_id)


def _settings_response(cap: int, comp: CompactionSettings) -> ChatSettings:
    return ChatSettings(
        attachment_inline_max_tokens=cap,
        compaction_enabled=comp.enabled,
        compaction_keep_recent=comp.keep_recent,
        compaction_min_tokens=comp.min_tokens,
    )


@router.get("/settings", response_model=ChatSettings)
async def get_chat_settings(request: Request) -> ChatSettings:
    """The operator's chat preferences (the runtime overrides, else the config defaults)."""
    store = deps.settings_store(request)
    cap = await get_attachment_inline_max_tokens(store, OPERATOR_ID)
    comp = await get_compaction(store, OPERATOR_ID)
    return _settings_response(cap, comp)


@router.put("/settings", response_model=ChatSettings)
async def update_chat_settings(body: ChatSettings, request: Request) -> ChatSettings:
    """Persist the operator's chat preferences. ``ge=0`` on the body rejects a bad value
    before it reaches the store. Omitted ``compaction*`` fields are left unchanged (merged
    over the current values), so a client tuning only one preference can't reset the rest."""
    store = deps.settings_store(request)
    if body.attachment_inline_max_tokens is not None:
        cap = await set_attachment_inline_max_tokens(
            store, OPERATOR_ID, body.attachment_inline_max_tokens
        )
    else:
        cap = await get_attachment_inline_max_tokens(store, OPERATOR_ID)
    current = await get_compaction(store, OPERATOR_ID)
    has_compaction = any(
        v is not None
        for v in (body.compaction_enabled, body.compaction_keep_recent, body.compaction_min_tokens)
    )
    if not has_compaction:
        return _settings_response(cap, current)
    comp = await set_compaction(
        store,
        OPERATOR_ID,
        CompactionSettings(
            enabled=current.enabled if body.compaction_enabled is None else body.compaction_enabled,
            keep_recent=current.keep_recent
            if body.compaction_keep_recent is None
            else body.compaction_keep_recent,
            min_tokens=current.min_tokens
            if body.compaction_min_tokens is None
            else body.compaction_min_tokens,
        ),
    )
    return _settings_response(cap, comp)
