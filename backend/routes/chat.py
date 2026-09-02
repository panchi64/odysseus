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

from collections.abc import Mapping, Sequence
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings

from agent import build_chat_orchestrator
from agent.summarize import AutoCompactPolicy, resolve_auto_compact_policy
from core.config import get_settings
from core.container import ServiceContainer
from core.exceptions import DegradedCapabilityError, NotFoundError
from routes import deps
from routes.deps import OPERATOR_ID
from runs import (
    CHAT_TURN_KINDS,
    DEFAULT_CONTEXT_THRESHOLDS,
    ContextThresholds,
    ConversationBusyError,
    RunRegistry,
)
from runs.registry import _UNSET
from services.conversations import ConversationBinding, ConversationStore
from services.modes import DEFAULT_MODE, ModeId, mode_spec
from services.permissions import PermissionLevel
from services.registry import ModelRegistry
from services.settings_store import (
    AUTO_COMPACT_KEEP_TURNS_MAX,
    AutoCompactSettings,
    get_agent_request_limit,
    get_agent_request_limit_override,
    get_auto_compact,
    get_context_thresholds,
    get_inactivity_timeout,
    get_wall_clock_timeout,
    set_agent_request_limit,
    set_auto_compact,
    set_context_thresholds,
    set_inactivity_timeout,
    set_wall_clock_timeout,
)
from services.uploads import UploadStore
from tools import InstructionProvider, PromptContextProvider

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
    # What kind of work a *new* thread is — the vocabulary and everything each mode
    # implies live in the registry (`services/modes.py`). "normal" and "research" run in
    # the conversation's own sandbox container; "code" runs in a git worktree of
    # `project_id`'s repository on the host. Both this and `project_id` are ignored when
    # continuing an existing conversation — the binding is set once, at creation, and a
    # thread's branch would be stranded if it could move.
    #
    # Deliberately **not** `code_mode`: `pydantic_ai_harness` ships a capability called
    # `CodeMode`, and it is an unrelated thing (a context-saving trick where the model
    # writes one script that calls many tools). This is a mode of the chat.
    mode: ModeId = DEFAULT_MODE
    project_id: str | None = None
    # How far the model may go this turn — and, unlike `mode`, from this turn onwards:
    # the level is persisted on the thread, so switching mid-conversation is a plain send
    # rather than a separate call, and a reload comes back at the level the operator left
    # it. Absent means "whatever the thread is already at" (a new thread starts at its
    # mode's default), so a client that never learned about levels keeps working.
    permission_level: PermissionLevel | None = None
    # Set when this turn is the operator resuming a turn a bound stopped (the
    # "Continue" button under a stop marker): the branch node id of the turn that
    # carries the marker. Accepting the turn retires that marker durably, so the
    # warning doesn't outlive the thing it was asking for. Ignored on a new
    # conversation — nothing there can be blocked yet.
    continues_message_id: str | None = None


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
    # Set when the conversation already had a live run and this message was queued
    # into it (to be injected at the run's next model-request boundary) instead of
    # starting a new run. Additive — a plain send never carries it.
    queued_message_id: str | None = None


class ChatSettings(BaseModel):
    """Operator-tunable chat preferences. The ``auto_compact*`` fields tune conversation
    compaction — the product's one context reduction: fold older *turns* into a
    utility-model summary once the context window fills.
    ``agent_request_limit`` is how many model round-trips one turn may spend before it
    stops. They're optional on a PUT — an omitted one is left unchanged — and always
    populated on a GET. snake_case out, matching the rest of the ``/chat`` surface.

    On a PUT, ``wall_clock_timeout_s`` is the one field where ``null`` is a *value* (no
    bound) rather than an omission, so the handler reads ``model_fields_set`` for it
    instead of testing against ``None`` like the rest. On a GET, ``null`` is meaningful in
    two fields, not one: an absent wall clock, and an ``inactivity_timeout_s`` a deploy
    disabled outright."""

    # `extra="forbid"` so a mistyped/unknown field is a 422, not a silent no-op: with every
    # field optional (omitted ⇒ unchanged), a typo'd key would otherwise be dropped and the PUT
    # would return 200 having changed nothing.
    model_config = ConfigDict(extra="forbid")

    # All fields are optional on a PUT (an omitted one is left unchanged) and always
    # populated on a GET; the bounds still reject a nonsensical value when one is provided.
    # Conversation auto-compaction: whether to fold older turns into a summary, and how
    # full the model's context window must get first. A **fraction**, not a percentage —
    # the same 0–1 quantity the context meter reports, so the client formats one number
    # rather than the wire carrying two conventions. Bounded above 0 (a 0 threshold would
    # fire on an empty thread) and at 1 (above it, compaction could never fire at all).
    auto_compact_enabled: bool | None = None
    auto_compact_threshold: float | None = Field(default=None, gt=0, le=1)
    # How many of the most recent exchanges the fold replays verbatim under the summary.
    # ``ge=0`` (unlike the threshold's ``gt=0``): 0 means "the summary is the whole replay",
    # which is a choice, not a nonsensical value. The ceiling exists because retaining the
    # whole thread would make the fold a no-op at the moment the thread is out of room.
    auto_compact_keep_turns: int | None = Field(
        default=None, ge=0, le=AUTO_COMPACT_KEEP_TURNS_MAX
    )
    # The context gauge's severity boundaries — the fullness at which the ring under the
    # composer turns amber, then red. Fractions, like the compaction threshold above and
    # for the same reason. The per-field bounds here only reject a value that is
    # nonsensical on its own; the pair's ordering (`warn` below `alert`) is checked
    # against the *merged* values in the PUT, since either may be omitted.
    context_warn_threshold: float | None = Field(default=None, gt=0, lt=1)
    context_alert_threshold: float | None = Field(default=None, gt=0, le=1)
    # ``ge=1``, not ``ge=0``: a turn allowed zero model requests could never produce an
    # answer, so 0 is a nonsensical value to accept rather than merely a minimal one.
    agent_request_limit: int | None = Field(default=None, ge=1)
    # The inactivity watchdog's bound in seconds: how long a run may go without emitting
    # an event before it is stopped. ``gt=0`` (a 0 bound would stop every turn
    # immediately); the config default applies when the operator hasn't set one, and a
    # deploy-level ``None`` disables the watchdog entirely.
    inactivity_timeout_s: float | None = Field(default=None, gt=0)
    # The wall-clock bound in seconds: how long a run may take in total, however busy it
    # is. Off unless the operator sets one — a turn is already bounded by
    # `agent_request_limit`, so a wall clock mostly stops runs that are merely slow. What
    # it does catch is a run that keeps emitting (a tool streaming progress, a model
    # streaming tokens) and so refreshes the inactivity watchdog forever without spending
    # a model request. ``gt=0`` for the same reason as above; ``null`` removes the bound.
    wall_clock_timeout_s: float | None = Field(default=None, gt=0)


async def resolve_turn_models(
    model_registry: ModelRegistry,
    endpoint_id: str | None,
    model: str | None,
    *,
    owner_id: str = OPERATOR_ID,
) -> tuple[Model, Model, ModelSettings | None, int | None, bool, int | None]:
    """Resolve the `main` model plus the background (utility/title) pair, raising a
    clear 4xx/503 on misconfiguration.

    Six values: the main model, the background model, its reasoning-off settings, the main
    model's context window, whether the main model reads images, and the background model's
    own context window. The last is here rather than resolved later because it is a
    property of a resolution only this function performs — and the summarizer, which is
    that background model, must be handed a transcript that fits inside it.

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
    # No context window, no turn. The window is discovered from the provider where the
    # provider will say (`ModelRegistry._with_context_windows`), so reaching here means
    # this one won't and the operator hasn't filled it in either.
    #
    # A hard stop rather than a degraded run, because every guard that keeps a thread
    # inside the model's limits measures against this number: the context gauge, the
    # auto-compaction trigger, and the overflow warning. Without it a long thread runs
    # normally right up until the provider rejects a request outright — no warning, no
    # fold, and the operator's first indication that anything was wrong is a failed
    # turn. Refusing up front is the honest version of that, and it names the fix.
    if main.context_window is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "this model's endpoint doesn't report a context window, so the "
                "conversation can't be kept inside it — set one on the endpoint under "
                "settings › models › advanced before sending"
            ),
        )
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
    # The background model's own window, defaulting to the main model's while the two are
    # the same model — an honest default rather than "unknown", since that is exactly what
    # it is when no `utility` endpoint is bound.
    utility_window = main.context_window
    if settings.verify_enabled or settings.title_enabled:
        background = await model_registry.resolve_background(
            owner_id=owner_id,
            override_endpoint_id=endpoint_id,
            override_model=model,
        )
        utility_model = background.model
        title_settings = background.reasoning_off
        utility_window = background.context_window
    return (
        resolved,
        utility_model,
        title_settings,
        main.context_window,
        main.vision,
        utility_window,
    )


async def _resolve_models(
    request: Request, endpoint_id: str | None, model: str | None
) -> tuple[Model, Model, ModelSettings | None, int | None, bool, int | None]:
    return await resolve_turn_models(deps.models(request), endpoint_id, model)


def compose_turn(
    *,
    prompt: str | None,
    conversation_id: str,
    models: tuple[Model, Model, ModelSettings | None, int | None, bool, int | None],
    capabilities: ServiceContainer,
    registry: RunRegistry,
    store: ConversationStore,
    uploads: UploadStore,
    categories: Mapping[str, Any] | None = None,
    instruction_providers: Sequence[InstructionProvider] = (),
    prompt_context_providers: Sequence[PromptContextProvider] = (),
    disabled_tools: frozenset[str] = frozenset(),
    binding: ConversationBinding | None = None,
    owner_id: str = OPERATOR_ID,
    attachment_ids: list[str] | None = None,
    ephemeral: bool = False,
    auto_compact: AutoCompactPolicy | None = None,
    request_limit: int | None = None,
    context_thresholds: ContextThresholds = DEFAULT_CONTEXT_THRESHOLDS,
    inactivity_timeout_s: float | None | object = _UNSET,
    wall_clock_timeout_s: float | None | object = _UNSET,
    kind: str = "chat",
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
    open after the answer — skip it by passing no title model.

    ``kind`` says who asked for the turn — the operator (``chat``, the default), the
    scheduler (``task``), or the agent itself (``linked``). Every one of them composes the
    identical orchestrator; the kind decides only which concurrency lane the run waits in
    (``runs/lanes.py``), so unattended work can never hold up the turn someone is sitting
    in front of."""
    resolved, utility_model, background_settings, context_window, vision, utility_window = models
    orchestrator = build_chat_orchestrator(
        prompt,
        model=resolved,
        categories=categories,
        instruction_providers=instruction_providers,
        prompt_context_providers=prompt_context_providers,
        utility_model=utility_model,
        utility_settings=background_settings,
        title_model=None if ephemeral else utility_model,
        title_settings=None if ephemeral else background_settings,
        context_window=context_window,
        # The operator's severity boundaries for that window. They decide only the
        # `level` on the emitted metrics — the gauge's colour — never the turn itself.
        context_thresholds=context_thresholds,
        capabilities=capabilities,
        store=store,
        conversation_id=conversation_id,
        uploads=uploads,
        attachment_ids=attachment_ids,
        vision=vision,
        # The operator's conversation-compaction policy; absent ⇒ the config defaults.
        auto_compact=auto_compact,
        # The summarizer runs on the background model, so its window is what bounds the
        # transcript a fold hands over.
        utility_context_window=utility_window,
        # The operator's per-turn model-request ceiling; absent ⇒ the config default.
        request_limit=request_limit,
        # While offline mode is active the web containers are down, so hide the web
        # tools from the agent rather than let it discover they're unavailable.
        disabled_tools=disabled_tools,
        # The thread's mode and project. Absent ⇒ an unfiled chat thread, which is what
        # a stateless or unattended turn is.
        binding=binding or ConversationBinding(),
    )
    try:
        run = registry.submit(
            kind=kind,
            owner_id=owner_id,
            orchestrator=orchestrator,
            conversation_id=conversation_id,
            # The operator's inactivity bound, resolved by the interactive caller; the
            # unattended task path omits it (_UNSET) and the registry default applies.
            inactivity_timeout_s=inactivity_timeout_s,
            # Same shape for the wall clock — resolved by the interactive caller, _UNSET
            # elsewhere. Both defaults are off, so an unattended turn is unbounded in
            # wall-clock terms unless the deploy set `run_wall_clock_timeout_s`.
            wall_clock_timeout_s=wall_clock_timeout_s,
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
    models: tuple[Model, Model, ModelSettings | None, int | None, bool, int | None],
    attachment_ids: list[str] | None = None,
    ephemeral: bool = False,
) -> ChatCreated:
    """Gather this route's resources from the `Request` and hand off to `compose_turn`.

    Async only because the enabled-tool policy is a persisted read; every other resource
    here is an `app.state` handle. `compose_turn` itself stays synchronous, so the
    submit remains a single uninterrupted step after the caller's conversation mutation."""
    # Read once and used twice — the mode decides which tools belong in this run as well
    # as where its file work happens, and the two must never be resolved separately.
    binding = await deps.store(request).binding(conversation_id)
    return compose_turn(
        prompt=prompt,
        conversation_id=conversation_id,
        models=models,
        # The app's one agent-facing capability bag — assembled at startup from every
        # feature manifest's `capabilities` export, so a turn never enumerates handles.
        capabilities=deps.capabilities(request),
        registry=deps.registry(request),
        store=deps.store(request),
        uploads=deps.uploads(request),
        # The assembled tool catalog + the manifests' dynamic instructions — read per
        # request so the turn always runs against what the app assembled.
        categories=deps.tool_categories(request),
        instruction_providers=deps.instruction_providers(request),
        prompt_context_providers=deps.prompt_context_providers(request),
        # `models[4]` is the resolved main model's vision fact — the same one
        # `compose_turn` passes to the engine for attachments. A tool that answers with
        # an image is withheld from a model that can't read one.
        disabled_tools=await deps.disabled_tools(
            request, binding.mode, permission=binding.permission, vision=models[4]
        ),
        binding=binding,
        attachment_ids=attachment_ids,
        ephemeral=ephemeral,
        # Resolved here, not at each caller, for the same reason as the request limit
        # below: send, regenerate and edit all want it and none of them should have to
        # know it exists.
        auto_compact=await _resolve_auto_compact(request, conversation_id),
        # Resolved here rather than at each caller so every interactive turn — send,
        # regenerate, edit — runs under the operator's ceiling without threading it
        # through three call sites. The *override*, not the effective number: a mode's
        # floor may raise a bound nobody chose, and must not overrule one they did.
        request_limit=await get_agent_request_limit_override(
            deps.settings_store(request), OPERATOR_ID
        ),
        # Same again for the context gauge's boundaries: resolved once here so send,
        # regenerate and edit all report severity against the operator's own pair.
        context_thresholds=await get_context_thresholds(deps.settings_store(request), OPERATOR_ID),
        # Same reason as the request limit: every interactive turn runs under the
        # operator's inactivity bound (else the config default).
        inactivity_timeout_s=await get_inactivity_timeout(
            deps.settings_store(request), OPERATOR_ID
        ),
        # And the wall clock, which is normally absent — resolved here anyway so that an
        # operator who does set one gets it on every interactive turn, not just send.
        wall_clock_timeout_s=await get_wall_clock_timeout(
            deps.settings_store(request), OPERATOR_ID
        ),
    )


async def _validate_attachments(request: Request, attachment_ids: list[str]) -> None:
    """Every attached id must name an upload the operator owns — reject foreign/unknown
    ids with a clear 404 rather than silently dropping them at run time."""
    if not attachment_ids:
        return
    # Cheap ownership check — decrypts nothing (resolve_attachments opens the bytes/text
    # later, only for ids that survive to run time) — and one query for the whole list,
    # since a turn with several files would otherwise pay a thread hop per id.
    owned = await deps.uploads(request).owned_ids(OPERATOR_ID, attachment_ids)
    for upload_id in attachment_ids:
        if upload_id not in owned:
            raise HTTPException(status_code=404, detail=f"attachment {upload_id!r} not found")


async def _resolve_auto_compact(request: Request, conversation_id: str | None) -> AutoCompactPolicy:
    """The effective conversation auto-compaction policy for a turn: the thread's on/off
    override beats the operator's global default, which beats the config default —
    resolved here rather than in the engine so the orchestrator never reads the settings
    store itself."""
    override = (
        await deps.store(request).get_compaction_override(conversation_id)
        if conversation_id is not None
        else None
    )
    return await resolve_auto_compact_policy(
        deps.settings_store(request), OPERATOR_ID, override=override
    )


def _enqueue_steering(
    registry: RunRegistry, conversation_id: str, body: ChatCreate
) -> ChatCreated | None:
    """Queue a mid-run message into the conversation's live chat run, or None when
    the busy conversation can't take one (the claim is held by a regenerate/edit
    with no run registered yet, the run isn't a chat turn, or the send carries
    attachments — steering is text-only). Synchronous end to end: no ``await``
    between finding the run and enqueueing, so the run can't reach terminal (or
    drain) in between.

    "Is a chat turn" is membership in the composed kinds, not equality with ``chat``: a
    scheduled task's run and a research thread the agent opened both drive a conversation
    the operator can open and both drain the queued-message inbox, so both take steering.
    Only a run some other orchestrator submitted — which would never read the queue — is
    refused."""
    if body.attachment_ids:
        return None
    run = registry.active_run_for(conversation_id, OPERATOR_ID)
    if run is None or run.kind not in CHAT_TURN_KINDS:
        return None
    message = run.enqueue_message(body.prompt)
    return ChatCreated(
        run_id=run.id,
        conversation_id=conversation_id,
        queued_message_id=message.id,
    )


async def _retire_stop_marker(
    store: ConversationStore, conversation_id: str, body: ChatCreate
) -> None:
    """Clear the stop marker this turn resumes, if it says it resumes one.

    Best-effort, and deliberately loose about *which* marker: the store resolves an id
    it doesn't recognize to the newest stop on the thread, because a live client names
    a turn that stopped before anything persisted by its own optimistic id. The cost of
    that latitude is a stale client — one whose turn was since deleted or regenerated —
    retiring a newer stop instead of the one it meant. That is a marker the operator
    loses, never a turn: the resume they asked for still runs either way."""
    if body.continues_message_id is None:
        return
    await store.clear_blocked_reason(conversation_id, body.continues_message_id)


async def _validate_new_thread_binding(request: Request, body: ChatCreate) -> None:
    """Reject a thread that could not work, before anything is created.

    A mode whose workspace is a git worktree needs a real project the operator owns,
    because that is what supplies the repository the worktree is cut from. And an
    **ephemeral** thread cannot have one: the compare panes are throwaway scratch threads,
    and each one would mint a git branch nobody ever looks at.
    """
    if body.project_id is not None:
        # 404 rather than a silent unfiled thread: filing work under a project that
        # doesn't exist would put it somewhere the operator will never look for it.
        try:
            await deps.projects(request).get(OPERATOR_ID, body.project_id)
        except NotFoundError:
            raise HTTPException(status_code=404, detail="project not found") from None
    if mode_spec(body.mode).workspace != "worktree":
        return
    if body.ephemeral:
        raise HTTPException(
            status_code=422, detail=f"an ephemeral conversation cannot use {body.mode} mode"
        )
    if body.project_id is None:
        raise HTTPException(
            status_code=422, detail=f"{body.mode} mode requires a project_id"
        )


@router.post("", status_code=202, response_model=ChatCreated)
async def create_chat(body: ChatCreate, request: Request) -> ChatCreated:
    # A turn needs *something* to act on: text, or at least one attached file ("here,
    # look at this").
    if not body.prompt.strip() and not body.attachment_ids:
        raise HTTPException(status_code=422, detail="prompt must not be empty")
    await _validate_attachments(request, body.attachment_ids)
    if body.conversation_id is None:
        await _validate_new_thread_binding(request, body)

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
            OPERATOR_ID,
            ephemeral=body.ephemeral,
            mode=body.mode,
            # Absent, the mode's own default decides what a fresh thread may do.
            permission=body.permission_level,
            # A thread files itself under whatever the request scope resolved — the
            # explicit `project_id` when the client sent one (code mode always does),
            # else the operator's active project, else unfiled.
            project_id=body.project_id or await deps.active_project(request),
        )

    # Claim now, before the remaining awaits (the auto-compaction policy resolve) and
    # the eventual `submit` below — a plain "is there a live run" check alone leaves a
    # gap a concurrent regenerate/edit/delete could occupy without ever registering a
    # run for `active_run_for` to see. A brand-new conversation's id is unknown to
    # anyone else yet, so this always succeeds for it.
    #
    # A busy conversation is not always a rejection: when the claim is held by a live
    # *chat* run (not a regenerate/edit claim) and the send is plain text, the message
    # queues into that run for injection at its next model-request boundary. The
    # check-and-enqueue is synchronous, so the run can't go terminal in between; and a
    # run that went terminal just before the POST simply lets the claim succeed — the
    # client never has to pick between "queue" and "new turn".
    registry = deps.registry(request)
    try:
        registry.claim(conversation_id, OPERATOR_ID)
    except ConversationBusyError:
        queued = _enqueue_steering(registry, conversation_id, body)
        if queued is not None:
            await _retire_stop_marker(store, conversation_id, body)
            return queued
        raise HTTPException(status_code=409, detail=_CONVERSATION_BUSY_DETAIL) from None
    try:
        # The one binding fact a later turn may change, written now that this request owns
        # the thread and *before* `_submit_turn` reads the binding — so this send runs at
        # the level it asked for, and the next one inherits it. Deliberately after the
        # claim: a send that is rejected as busy, or diverted into the live run as
        # steering, never gets a turn of its own to run at the new level, and moving the
        # stored one anyway would leave the operator's control reading a level nothing is
        # actually running at.
        if body.conversation_id is not None and body.permission_level is not None:
            await store.set_permission_level(conversation_id, body.permission_level)
        created = await _submit_turn(
            request,
            prompt=body.prompt,
            conversation_id=conversation_id,
            models=models,
            attachment_ids=body.attachment_ids,
            ephemeral=body.ephemeral,
        )
        # Only once the run is submitted — a rejected send leaves the operator with the
        # same unfinished turn, so it must leave them the marker too. The claim above is
        # not enough to know that: `submit` has its own atomic check-and-claim, and a
        # race it catches becomes a 409 from in here.
        await _retire_stop_marker(store, conversation_id, body)
        return created
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
        return await _submit_turn(
            request,
            prompt=body.prompt,
            conversation_id=body.conversation_id,
            models=models,
            attachment_ids=body.attachment_ids,
        )
    finally:
        deps.release_conversation(request, body.conversation_id)


def _settings_response(
    auto: AutoCompactSettings,
    context: ContextThresholds,
    steps: int,
    inactivity: float | None,
    wall_clock: float | None,
) -> ChatSettings:
    return ChatSettings(
        auto_compact_enabled=auto.enabled,
        auto_compact_threshold=auto.threshold,
        auto_compact_keep_turns=auto.keep_turns,
        context_warn_threshold=context.warn,
        context_alert_threshold=context.alert,
        agent_request_limit=steps,
        inactivity_timeout_s=inactivity,
        wall_clock_timeout_s=wall_clock,
    )


@router.get("/settings", response_model=ChatSettings)
async def get_chat_settings(request: Request) -> ChatSettings:
    """The operator's chat preferences (the runtime overrides, else the config defaults)."""
    store = deps.settings_store(request)
    auto = await get_auto_compact(store, OPERATOR_ID)
    steps = await get_agent_request_limit(store, OPERATOR_ID)
    inactivity = await get_inactivity_timeout(store, OPERATOR_ID)
    wall_clock = await get_wall_clock_timeout(store, OPERATOR_ID)
    context = await get_context_thresholds(store, OPERATOR_ID)
    return _settings_response(auto, context, steps, inactivity, wall_clock)


@router.put("/settings", response_model=ChatSettings)
async def update_chat_settings(body: ChatSettings, request: Request) -> ChatSettings:
    """Persist the operator's chat preferences. The body's bounds reject a bad value before
    it reaches the store. Every field is optional and an omitted one is left unchanged —
    each multi-field group is merged over its current values and only written when the body
    touched it, so a client tuning one preference can't reset the rest."""
    store = deps.settings_store(request)
    if body.agent_request_limit is not None:
        steps = await set_agent_request_limit(store, OPERATOR_ID, body.agent_request_limit)
    else:
        steps = await get_agent_request_limit(store, OPERATOR_ID)
    if body.inactivity_timeout_s is not None:
        inactivity = await set_inactivity_timeout(store, OPERATOR_ID, body.inactivity_timeout_s)
    else:
        inactivity = await get_inactivity_timeout(store, OPERATOR_ID)
    # `null` here means "remove the bound", so presence in the body — not a non-None
    # value — is what says the client touched it.
    if "wall_clock_timeout_s" in body.model_fields_set:
        wall_clock = await set_wall_clock_timeout(store, OPERATOR_ID, body.wall_clock_timeout_s)
    else:
        wall_clock = await get_wall_clock_timeout(store, OPERATOR_ID)

    auto = await get_auto_compact(store, OPERATOR_ID)
    if (
        body.auto_compact_enabled is not None
        or body.auto_compact_threshold is not None
        or body.auto_compact_keep_turns is not None
    ):
        auto = await set_auto_compact(
            store,
            OPERATOR_ID,
            AutoCompactSettings(
                enabled=auto.enabled
                if body.auto_compact_enabled is None
                else body.auto_compact_enabled,
                threshold=auto.threshold
                if body.auto_compact_threshold is None
                else body.auto_compact_threshold,
                keep_turns=auto.keep_turns
                if body.auto_compact_keep_turns is None
                else body.auto_compact_keep_turns,
            ),
        )

    context = await get_context_thresholds(store, OPERATOR_ID)
    if body.context_warn_threshold is not None or body.context_alert_threshold is not None:
        warn = context.warn if body.context_warn_threshold is None else body.context_warn_threshold
        alert = (
            context.alert if body.context_alert_threshold is None else body.context_alert_threshold
        )
        # The ordering invariant is checked on the *merged* pair, not on the body: raising
        # `warn` above a stored `alert` is the ordinary way to invert them, and a body
        # carrying only that one field would satisfy every per-field bound.
        # `ContextThresholds` owns the rule; this turns its refusal into the 422 the field
        # bounds would have produced had the constraint been expressible on one field.
        try:
            thresholds = ContextThresholds(warn=warn, alert=alert)
        except ValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail=(
                    "the context warn threshold must be below the alert threshold "
                    f"(got warn {warn}, alert {alert})"
                ),
            ) from exc
        context = await set_context_thresholds(store, OPERATOR_ID, thresholds)
    return _settings_response(auto, context, steps, inactivity, wall_clock)
