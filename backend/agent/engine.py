"""The agent engine — the first real orchestrator on the Run substrate.

Wraps Pydantic AI's ``Agent`` and drives it via ``agent.iter()`` so the chassis
can observe every step and stream it (translation lives in ``translate.py``).
The library owns the within-turn loop, tool selection, validation, and fallback;
we own the run lifecycle, the event stream, bounds, and the approval pause/resume
for sensitive actions. The meta-loop (verifier/loop-break) lands here next.

A turn is driven by :func:`_drive_turn`, shared by the initial run and every
resume. When the model requests a sensitive (approval-required) tool, Pydantic AI
ends the turn with ``DeferredToolRequests`` *without executing it*; we surface
``approval.required``, park the Run (``awaiting_input``), and stash a
:class:`ParkedTurn` so an approve decision can resume exactly where it left off.
``ask_user`` takes the same road for the other reason a turn stops on the operator:
the call defers for an *answer* rather than a permission, and the answer they give
comes back as the call's own result.

What lives *here* is the turn's control flow and the two orchestrators that wrap it.
Five neighbours carry the concerns that aren't that, each with its own reason to change:

- ``history.py`` — the surgeries on a message list before it reaches a model or the
  store. Pure functions; each encodes one fact about how the library or a provider
  behaves.
- ``naming.py`` — when and how a fresh thread gets named, either concurrently with the
  answer or after a resume. (``title.py`` remains the model call itself.)
- ``flush.py`` — persisting a turn that was stopped from outside, shared by both
  orchestrators so a bound, a cancel and an unhandled exception cannot drift apart.
- ``model_errors.py`` — reading a provider's failure: which stop it is, and what the
  operator is told.
- ``gating.py`` — ruling on the calls a turn deferred: grants, the level's own answer,
  and the Auto level's review (announced on the stream). The rules it applies are
  ``services/permissions``'.
- ``parking.py`` — the continuation payload a parked turn resumes from, and the park
  itself (the approval and question events, and the notify that must land before it).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic_ai import (
    Agent,
    DeferredToolRequests,
    DeferredToolResults,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RunContext,
    RunUsage,
    UsageLimitExceeded,
    UsageLimits,
    UserPromptPart,
)
from pydantic_ai.capabilities import ReinjectSystemPrompt
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings

from core.config import get_settings
from core.container import ServiceContainer
from core.exceptions import ModelLoadError
from prompts.agent import (
    CURRENT_DATE,
    INSTRUCTIONS,
    SYSTEM_PROMPT,
    VERIFIER_NUDGE,
)
from runs import (
    DEFAULT_CONTEXT_THRESHOLDS,
    CompactionReason,
    CompactionStarted,
    ContextThresholds,
    ConversationCompacted,
    LimitNotice,
    Orchestrator,
    Run,
    RunMetrics,
    RunStatus,
    TurnOverhead,
    total_timings,
)
from services.context_budget import compose
from services.conversation_view import estimate_tokens
from services.conversations import (
    ConversationBinding,
    ConversationStore,
    context_footprint,
    conversation_totals,
    last_request_usage,
)
from services.llm import TOOL_CALL_SETTINGS
from services.modes import mode_spec
from services.notifications import NotificationService
from services.projects import ProjectStore, WorktreeManager
from services.sandbox import SandboxSessionManager
from services.tool_policy import vision_disabled_tools
from services.uploads import UploadStore
from services.workspace import resolve_workspace
from tools import (
    InstructionProvider,
    PromptContextProvider,
    RunDeps,
    build_agent_toolsets,
)

from .attachments import resolve_attachments
from .compaction_context import CompactionContext, resolve_max_input_tokens
from .flush import CANCELLED_DETAIL, PersistContext, TurnFlush
from .footprint import estimate_footprint, overhead_fallback_tokens
from .gating import settle_deferred
from .history import (
    drop_dangling_tool_calls,
    merge_consecutive_requests,
    split_injected_requests,
    with_tail_context,
)
from .injections import AnnounceInjections, announce_injection, contributor_id
from .meta import Judge, LoopBreaker, LoopDetected, make_utility_judge
from .model_errors import (
    CONTEXT_OVERFLOW_DETAIL,
    context_limit_message,
    is_context_overflow,
    model_load_hint,
    usage_limit_kind,
    usage_limit_message,
)
from .naming import (
    TitleContext,
    discard_title,
    maybe_title,
    settle_title,
    start_title,
)
from .overhead import MeasureOverhead
from .parking import DEFAULT_BINDING, ParkedTurn, park_for_input
from .summarize import (
    AutoCompactPolicy,
    build_auto_compact_policy,
    compact_conversation,
    should_compact,
)
from .title import last_user_text
from .translate import stream_agent_run

logger = logging.getLogger(__name__)

# A shared empty bag for the no-capabilities default — every capability-backed tool
# degrades uniformly. Never mutated (only construction sites add), so safe to share.
_NO_CAPS = ServiceContainer()


@dataclass
class _TurnResult:
    """What one turn produced: a final answer (or None if it parked/blocked/hit
    a bound) and the message history needed to continue the conversation."""

    answer: str | None
    messages: list[ModelMessage] = field(default_factory=list)
    # A verifier correction's [reject_idx, nudge_idx] range to drop on persist.
    clean_drop: tuple[int, int] | None = None
    # Set when the turn stopped at a bound (`run.status is blocked`) — the
    # human-readable reason, carried through to `_finalize` so it can persist a
    # marker on the turn's branch node (see `ConversationStore.record`).
    blocked_reason: str | None = None


def _build_agent(
    model: Model,
    *,
    categories: Any = None,
    instruction_providers: Sequence[InstructionProvider] = (),
) -> Agent:
    # Two prompt seams by durability: SYSTEM_PROMPT (identity/voice) is anchored in
    # history; INSTRUCTIONS (autonomy, tool posture, the treat-external-content-as-
    # data guardrail) are rebuilt fresh from the agent every turn, so a poisoned or
    # reconstructed history can never displace them. ReinjectSystemPrompt keeps the
    # system prompt — the half that *does* live in history — authoritative too,
    # stripping any spoofed system part and reasserting ours on every request.
    # output_type accepts DeferredToolRequests so approval-required tools can defer
    # instead of executing; normal turns still return text.
    agent = Agent(
        model,
        deps_type=RunDeps,
        system_prompt=SYSTEM_PROMPT,
        instructions=INSTRUCTIONS,
        toolsets=build_agent_toolsets(categories),
        # Parallel tool calling (see `services.llm.TOOL_CALL_SETTINGS`). Declared at
        # construction, not per-run on `agent.iter(...)`: a park stashes this agent on
        # the ParkedTurn, so every resume inherits it with nothing threaded through the
        # payload. The library merges run-level settings over these, so it's a default
        # a future per-run knob can still override.
        model_settings=TOOL_CALL_SETTINGS,
        output_type=[str, DeferredToolRequests],
        # ReinjectSystemPrompt keeps our system prompt authoritative — it transforms only
        # what the model sees, never what we persist. Nothing else rewrites the history on
        # its way to the model: a tool result rides into context whole, and the one
        # reduction that exists (conversation compaction) fires between turns, in the
        # orchestrator prelude, against measured context pressure.
        # `MeasureOverhead` and `AnnounceInjections` are listed *after*
        # `ReinjectSystemPrompt` so they read the request as it actually ships rather than
        # before the system prompt is reasserted. Both observe and return the request
        # context untouched, and they are two capabilities rather than one pass over the
        # same parts because they answer different questions and change for different
        # reasons: one sizes the brief for the gauge, the other reports what it said.
        capabilities=[
            ReinjectSystemPrompt(replace_existing=True),
            MeasureOverhead(),
            AnnounceInjections(),
        ],
    )

    # Feature-contributed dynamic instructions (each manifest's `instructions` export —
    # the skill catalog): re-resolved fresh each turn, so they're always current and,
    # unlike an appended prompt, never accumulate in history. Each resolves its own
    # capability from the run's bag and no-ops (returns "") when the capability isn't
    # wired, so registration is unconditional. Instructions render at the *head* of
    # every request — keep them small and low-churn, or they invalidate the inference
    # engine's prompt-prefix cache for the whole history behind them (volatile context
    # belongs in a manifest's `prompt_context` export instead, delivered at the tail).
    #
    # `name=` is what makes the context readout's per-provider rows possible: the library
    # stamps the resolved part with that name, so `agent/overhead.py` reads each block off
    # the assembled request instead of measuring providers as they run — and
    # `agent/injections.py` reads the same name to announce what the block said.
    for provider in instruction_providers:
        agent.instructions(name=contributor_id(provider))(provider)

    @agent.instructions(name="mode")
    def _mode_posture(ctx: RunContext[RunDeps]) -> str:
        """The thread's mode, where it has something of its own to say — read off the
        registry, so a mode's prose lives with the rest of that mode's declaration rather
        than in a branch here. Most modes add nothing and resolve to "" (see
        `prompts/modes.py`), which is why this is unconditional."""
        return mode_spec(ctx.deps.mode).instructions

    @agent.instructions(name="date")
    def _current_date() -> str:
        """Give the agent today's date as a dynamic instruction — re-resolved fresh each
        turn (always current, no stale pinned copy) and kept out of history. Uses the
        host's local timezone, the operator's own clock on their own hardware."""
        now = datetime.now().astimezone()
        # Avoid strftime "%-d"/"%#d" platform splits — build the day number directly so
        # this stays portable across POSIX hosts.
        stamp = f"{now:%A, %B} {now.day}, {now.year}"
        return CURRENT_DATE.format(date=stamp)

    return agent


def _turn_metrics(run: Run, messages: list[ModelMessage]) -> RunMetrics:
    """The thread's cumulative readout, counted off ``messages`` — the full replayed
    history, not just this run's own additions.

    **Derived, not accumulated.** ``messages`` is everything on the active path, and
    each stored response carries the usage the provider reported for it, so every count
    and token here is a fresh sum over the path. That is what makes the figures survive
    a reload, a rewind and a version switch without a counter to keep in step: the same
    ``conversation_totals`` runs on a cold load and produces the same answer. It is also
    why this no longer takes a ``base``/``usage`` pair — the run's own ``RunUsage``
    covers only the current run, and adding it to a path-derived total would count this
    turn twice.

    Time is the exception, and the only thing still carried on the Run: it isn't in the
    message blobs. ``run.prior_timings`` holds the persisted total for the turns before
    this one, and ``run.timer`` holds this run's own, so the two add.

    ``context_used`` is the *footprint* — the last response's prompt+generation, not the
    path's summed tokens — so a long thread doesn't overstate fullness. Built in one
    place so the live per-step frames (the context gauge) and the stashed terminal
    metrics never diverge.

    **Fold-aware.** A response that landed *before* this run's most recent compaction
    reported its prompt size against a history that no longer exists, so the footprint is
    read only from ``run.fold_boundary`` onward. Until the first post-fold response lands
    there is nothing measured to read, and the estimate stands in — which is the whole
    point: without it the gauge would sit pinned at the pre-fold figure through the very
    turn the fold made room for, and the operator would watch a compaction change nothing.
    ``last_request_usage`` still reads the whole path: which model spoke last, and what its
    cache did, are facts about a request, not about the current replay."""
    counts = conversation_totals(messages)
    timings = run.prior_timings + total_timings(run.timer.responses)
    # The boundary decides which *reported* figures may still be believed, not what the
    # estimate covers: the estimate is always over the whole replay, because the whole
    # replay is what the next request carries.
    footprint = context_footprint(messages[min(run.fold_boundary, len(messages)) :])
    if footprint is None and messages:
        footprint = estimate_footprint(
            messages,
            run.context_overhead,
            fallback_overhead_tokens=overhead_fallback_tokens(get_settings()),
        )
    return RunMetrics(
        steps=counts.steps,
        tool_calls=counts.tool_calls,
        turns=counts.turns,
        input_tokens=counts.input_tokens,
        output_tokens=counts.output_tokens,
        cache_read_tokens=counts.cache_read_tokens,
        # A thread whose responses all predate the stopwatch reports no time rather
        # than none-elapsed — the same absent-not-zero rule the token counts follow.
        llm_ms=timings.llm_ms or None,
        tool_ms=timings.tool_ms or None,
        ttft_ms_total=timings.ttft_ms_total or None,
        ttft_samples=timings.ttft_samples,
        context_window=run.context_window,
        context_used=footprint,
        context_thresholds=run.context_thresholds,
        # The split of that footprint. Scaled to the provider's own total, so the parts
        # always add up to the figure beside them even though each is an estimate.
        context_parts=compose(footprint, run.context_overhead, messages),
        # The last request on its own — read off the same path as everything else, so a
        # reload reports the route and the cache figures the live turn did.
        last_request=last_request_usage(messages),
    )


def _incoming_request(
    user_prompt: str | list[Any] | None, extra: list[str]
) -> ModelRequest | None:
    """This turn's own new content as one request, for measuring it — the operator's
    message with its attachment markers, plus any per-turn context that isn't already
    inside it (a regenerate has no fresh prompt, so its context is the only new part).

    ``None`` when the turn adds nothing measurable, which is a plain regenerate with no
    context providers wired. Binary parts ride along untouched; the estimator ignores
    them by design."""
    parts: list[Any] = []
    if user_prompt is not None:
        parts.extend(user_prompt if isinstance(user_prompt, list) else [user_prompt])
    parts.extend(extra)
    return ModelRequest(parts=[UserPromptPart(content=parts)]) if parts else None


async def _fold(
    run: Run, ctx: CompactionContext, *, reason: CompactionReason
) -> list[ModelMessage] | None:
    """Run one compaction and announce it, returning the replay it leaves behind — or
    ``None`` when nothing folded.

    The one path every fold takes, whichever of the two triggers fired, so the pair cannot
    drift on what is emitted or in what order. Nothing here may raise: both callers are on
    the critical path of a turn, and compaction is an efficiency measure rather than a
    guard — when it fails, or frees nothing, the turn carries on and meets the model's real
    ceiling, which is the honest outcome.

    ``compaction.started`` goes out from inside the plan callback rather than before it, so
    it is emitted only once there is genuinely something to fold and can state what. It
    also refreshes the inactivity watchdog on the way past, which matters more than it
    looks: the summarizer is a whole model call with its own timeout, and it emits nothing
    while it runs."""
    try:
        outcome = await compact_conversation(
            ctx.store,
            ctx.conversation_id,
            model=ctx.model,
            reasoning_off=ctx.reasoning_off,
            keep_turns=ctx.policy.keep_turns,
            settings=ctx.settings,
            max_input_tokens=ctx.max_input_tokens,
            on_plan=lambda plan: run.emit(
                CompactionStarted(
                    conversation_id=ctx.conversation_id,
                    reason=reason,
                    messages=len(plan.messages),
                    tokens_estimate=estimate_tokens(plan.messages),
                )
            ),
        )
    except Exception:  # noqa: BLE001 — an optimization must never take the turn down with it
        logger.warning("compaction failed for %s", ctx.conversation_id, exc_info=True)
        return None
    if outcome is None:
        return None
    run.emit(
        ConversationCompacted(
            conversation_id=ctx.conversation_id,
            reason=reason,
            message_id=outcome.message_id,
            summary=outcome.summary,
            messages_compacted=outcome.messages_compacted,
            tokens_before=outcome.tokens_before,
            tokens_after=outcome.tokens_after,
            after_message_id=outcome.after_message_id,
        )
    )
    return await ctx.store.model_history(ctx.conversation_id)


async def _maybe_compact(
    run: Run,
    ctx: CompactionContext | None,
    history: list[ModelMessage],
    *,
    overhead: TurnOverhead | None,
    incoming_tokens: int,
    context_window: int | None,
) -> tuple[list[ModelMessage], bool]:
    """Fold this conversation's older turns when the turn *about to run* would reach the
    operator's share of the model's context window, returning the history to replay and
    whether anything folded.

    The trigger is projected, not retrospective: ``incoming_tokens`` is this turn's own
    prompt, its attachments and the per-turn context appended to it, all of which are
    resolved before this runs precisely so they can be counted here. A thread at 70% that
    is about to be handed a 15% prompt is a thread that needs folding now, and measuring
    the history alone could not see that.

    Returns ``history`` unchanged whenever compaction is off, unmeasurable (no declared
    window), not yet due, has nothing left to fold, or the summarizer failed."""
    if ctx is None or not ctx.policy.enabled:
        return history, False
    if not should_compact(
        history,
        context_window,
        ctx.policy.threshold,
        overhead=overhead,
        incoming_tokens=incoming_tokens,
        settings=ctx.settings,
    ):
        return history, False
    folded = await _fold(run, ctx, reason="threshold")
    return (history, False) if folded is None else (folded, True)


def _without_empty_tail(messages: list[ModelMessage]) -> list[ModelMessage]:
    """Drop the empty response the streaming path leaves behind when a request fails.

    Pydantic AI appends a placeholder ``ModelResponse`` to the history before it starts
    streaming into it, so a request the provider refuses outright leaves a partless
    response as the tail. It is not a message — nothing was generated — and leaving it
    there would end the rebuilt history on a response, which is not a shape a turn can be
    resumed from."""
    while messages and isinstance(messages[-1], ModelResponse) and not messages[-1].parts:
        messages = messages[:-1]
    return messages


async def _compact_and_retry(
    run: Run,
    ctx: CompactionContext,
    *,
    partial_history: list[ModelMessage],
    start_ref: list[int],
) -> list[ModelMessage] | None:
    """Fold the thread mid-turn and rebuild the history the failed request will be re-sent
    against, or ``None`` when nothing folded.

    The turn's own messages are not recorded yet, so the tree's leaf is still the previous
    tip and the checkpoint lands exactly where the prelude's fold would have put it. What
    the model replays afterwards is the folded history *plus this turn so far* — the
    operator's prompt, the tool calls it has already made and their results, none of which
    is in the tree yet and all of which the retried request depends on.

    The order below is load-bearing:

    - the dangling-call strip runs on the folded history alone, because a *retained* turn
      that once stopped at a bound can end on an unanswered tool call, and this turn's own
      trailing call is answered by the very request being retried;
    - the merge runs over the **concatenation**, because the library merges consecutive
      requests when it cleans a history it is resuming, and a checkpoint hoisted in front
      of a turn that opens on a user prompt is exactly that shape. Pre-merging is what
      keeps ``all_messages()`` the length we measured our index against;
    - the index is then re-derived from the tail rather than from the fold, so it is right
      whether or not the merge collapsed the boundary.

    An operator who switched compaction off for this thread is not overruled by an
    overflow: they get the stop, and the **Compact and retry** it offers, which is the
    same fold under their own hand.
    """
    if not ctx.policy.enabled:
        return None
    folded = await _fold(run, ctx, reason="overflow")
    if folded is None:
        return None
    turn_slice = _without_empty_tail(partial_history[start_ref[0] :])
    rebuilt = merge_consecutive_requests([*drop_dangling_tool_calls(folded), *turn_slice])
    start_ref[0] = len(rebuilt) - len(turn_slice)
    # Every response still in front of the turn is pre-fold, so the gauge must not read a
    # footprint off one until this turn answers.
    run.fold_boundary = start_ref[0]
    return rebuilt


async def _drive_turn(
    run: Run,
    agent: Agent,
    *,
    prompt: str | list[Any] | None = None,
    message_history: list[ModelMessage] | None = None,
    deferred_results: DeferredToolResults | None = None,
    announced: set[str],
    caps: ServiceContainer = _NO_CAPS,
    conversation_id: str | None = None,
    disabled_tools: frozenset[str] = frozenset(),
    binding: ConversationBinding = DEFAULT_BINDING,
    vision: bool = True,
    partial_history_ref: list[Callable[[], list[ModelMessage]]] | None = None,
    store: ConversationStore | None = None,
    request_limit: int | None = None,
    compaction: CompactionContext | None = None,
    start_ref: list[int] | None = None,
    correcting: bool = False,
) -> _TurnResult:
    """Drive one turn to its end: an answer, a park, or a stop at a bound.

    ``start_ref`` is the caller's persistence index — the position in the replayed history
    at which *this turn's* own messages begin — held in a one-element list because an
    in-turn fold moves it. Every reader of that index (the completed persist, the flush
    hooks, a park) reads it through this list, so a fold cannot leave one of them slicing
    against the pre-fold history.

    ``compaction`` is what this turn may fold with, or ``None`` for a turn that cannot fold
    (a stateless run, or compaction switched off). ``correcting`` marks a verifier's
    corrective re-attempt, where a fold is refused: the correction's drop range is a pair
    of absolute indices into the pre-fold history, and folding underneath it would leave
    the persist dropping two messages that are no longer the ones it meant."""
    settings = get_settings()
    spec = mode_spec(binding.mode)
    # ``request_limit`` is the operator's runtime setting *when they set one*; None means
    # nobody chose a number here (they never touched the control, or this is a stateless
    # eval turn / an older parked payload). It bounds *model round-trips*, so every tool
    # call spends one.
    #
    # The mode's floor applies to the number nobody chose, and only to that one. A mode
    # whose work genuinely cannot fit inside the shipped default would otherwise stop at a
    # bound nothing about this deployment picked; but an operator who deliberately lowered
    # the ceiling to 10 must not find a research turn taking 60 round trips while the
    # settings page still reads 10. Unset is a floor to raise; set is an answer to honour.
    resolved_limit = (
        max(settings.agent_request_limit, spec.request_limit or 0)
        if request_limit is None
        else request_limit
    )
    limits = UsageLimits(
        request_limit=resolved_limit,
        tool_calls_limit=settings.agent_tool_calls_limit,
    )
    deps = RunDeps(
        run=run,
        owner_id=run.owner_id,
        # The whole agent-facing capability bag rides in as one handle — a tool
        # resolves what it needs by type and degrades when it's absent.
        caps=caps,
        disabled_tools=disabled_tools,
        conversation_id=conversation_id,
        # Where this run's file work happens. Resolved from the *conversation's* stored
        # binding by the caller, never from a live request — switching the active project
        # must not change what an already-running thread is doing.
        project_id=binding.project_id,
        mode=binding.mode,
        # And how far it may go on its own. The toolset stack reads this to mark the tools
        # that reach past it, so the level is enforced before a call runs rather than
        # apologised for afterwards.
        permission=binding.permission,
    )
    # A turn may run as several segments: the initial model pass, then a continuation
    # for each batch of deferred calls a conversation grant auto-approves. They share
    # ONE usage budget, ONE no-progress guard, and ONE usage accumulator, so the *whole*
    # turn is bounded — a granted tool the model keeps re-calling can't reset the guards
    # (or grow the call stack) by deferring on each hop; it trips the loop/usage stop.
    loop_breaker = LoopBreaker(repeat_threshold=settings.loop_repeat_threshold)
    usage = RunUsage()

    def report_progress(history: list[ModelMessage]) -> None:
        # A live context/usage frame as each model response lands, so the operator's context
        # gauge fills in real time during a live turn. Also the loop's cooperative-cancel
        # check: `RunRegistry.cancel()` sets `cancel_requested` and then hard-cancels the
        # task immediately, so in practice the native cancellation almost always lands first —
        # this is a redundant, independent stop path for the rare case something upstream
        # swallows that CancelledError (e.g. a tool/dependency catching too broadly), so a
        # requested cancel can never be silently absorbed.
        if run.cancel_requested:
            raise asyncio.CancelledError()
        run.emit(_turn_metrics(run, history))

    # Rebound each loop iteration by `agent.iter()`'s `as agent_run`; stays None only
    # if a bound trips before the context manager assigns it (its `__aenter__` does
    # no request, so this hasn't been observed, but the except blocks below guard
    # it anyway rather than risk an unbound-variable crash on a stop path).
    agent_run: Any = None

    def _partial_history() -> list[ModelMessage]:
        return list(agent_run.ctx.state.message_history) if agent_run is not None else []

    def _inject_queued(node: Any) -> None:
        # Mid-run steering: hand any operator messages queued since the last model
        # request to the model *now*, by amending the not-yet-sent request. The node
        # is yielded before it streams (its request isn't in history yet), so this
        # never touches an in-flight model stream; a request mixing tool returns
        # with these user parts is split back into separate messages on persist
        # (`_split_injected_requests`), which replays wire-identically because the
        # library re-merges consecutive requests at wire-prep.
        #
        # Rebinds `parts` to a NEW list rather than appending in place. On a regenerate
        # the node's request is built by the library reusing the *same* parts list object
        # as the last history message — which the store handed out by reference from its
        # in-memory tree. Appending would therefore graft the steering text into the
        # operator's original user bubble for every later replay. Same invariant
        # `_with_tail_context` documents: never mutate what the store shares.
        queued = run.drain_messages()
        if queued:
            node.request.parts = [
                *node.request.parts,
                *(UserPromptPart(message.text) for message in queued),
            ]

    if partial_history_ref is not None:
        # Let the caller reach this turn's current partial state at any point — even
        # before the first step lands — so an external timeout mid-turn can still flush
        # whatever's there (see `build_chat_orchestrator`'s `on_timeout` hook).
        partial_history_ref[:] = [_partial_history]

    # One recovery per turn. A second overflow after a fold means the request is oversized
    # for a reason folding cannot reach (one enormous tool result, an attachment that
    # doesn't fit), and re-folding would strip the thread's memory for nothing.
    compacted = False

    while True:
        # Same cooperative-cancel check as `report_progress`, at the turn-segment
        # boundary between an auto-approved tool's continuation and the next model
        # round-trip (see that function's comment for why this is a redundant,
        # not primary, stop path).
        if run.cancel_requested:
            raise asyncio.CancelledError()
        try:
            async with agent.iter(
                prompt,
                deps=deps,
                message_history=message_history,
                deferred_tool_results=deferred_results,
                usage_limits=limits,
                usage=usage,
            ) as agent_run:
                await stream_agent_run(
                    agent_run,
                    run,
                    announced=announced,
                    loop_breaker=loop_breaker,
                    on_step=report_progress,
                    on_request_node=_inject_queued,
                )
                result = agent_run.result
        except UsageLimitExceeded as exc:
            # Hit a usage bound — stop and report state, don't error. The *same* sentence
            # is both the toast and the persisted stop marker: a bare "usage limit reached"
            # reads as a provider rate limit (the operator's first guess, and the wrong
            # one), where this names the bound that actually tripped — one of this run's
            # own local budgets.
            detail = usage_limit_message(exc)
            run.emit(LimitNotice(limit=usage_limit_kind(exc), message=detail))
            run.block(detail)
            return _TurnResult(
                answer=None,
                messages=_partial_history(),
                blocked_reason=detail,
            )
        except LoopDetected as exc:
            # No-progress guard tripped — stop and report state, don't error.
            run.emit(LimitNotice(limit="loop", message=str(exc)))
            detail = "stopped: repeated an action without making progress"
            run.block(detail)
            return _TurnResult(
                answer=None,
                messages=_partial_history(),
                blocked_reason=detail,
            )
        except ModelHTTPError as exc:
            # Context-window overflow. The request that overran is still the tail of the
            # partial history and would replay on every later turn, so this cannot simply
            # be reported: fold the thread once and re-send the same request against the
            # summary. If there is nothing to fold, folding is refused here, or the retry
            # overruns again, it is a definitive ceiling — stop and name it, rather than
            # papering over it by silently dropping content.
            if is_context_overflow(exc):
                rebuilt = (
                    None
                    if compacted or correcting or compaction is None or start_ref is None
                    else await _compact_and_retry(
                        run, compaction, partial_history=_partial_history(), start_ref=start_ref
                    )
                )
                if rebuilt is not None:
                    compacted = True
                    # The resume-without-prompt shape: the library pops the trailing
                    # request and re-sends its parts, so the very request that overran is
                    # the one retried — against the folded history in front of it.
                    prompt = None
                    message_history = rebuilt
                    deferred_results = None
                    continue
                run.emit(
                    LimitNotice(
                        limit="context", message=context_limit_message(run, compacted=compacted)
                    )
                )
                run.block(CONTEXT_OVERFLOW_DETAIL)
                return _TurnResult(
                    answer=None,
                    messages=_partial_history(),
                    blocked_reason=CONTEXT_OVERFLOW_DETAIL,
                )
            # Rewrite a model-couldn't-load error into something the operator can act
            # on; let every other HTTP error propagate with its own detail.
            hint = model_load_hint(exc)
            if hint is None:
                raise
            raise ModelLoadError(hint) from exc

        output = result.output
        messages = result.all_messages()
        # Counted off the full replayed history, so hops and segments need no
        # accumulator — see `_turn_metrics`.
        run.set_metrics(_turn_metrics(run, messages))
        # Two ways a turn can end without being finished: a call awaiting permission, and
        # a call awaiting an answer (`ask_user`). Both arrive on the same object, and
        # either one alone means there is more of this turn to run.
        deferred = isinstance(output, DeferredToolRequests) and (
            output.approvals or output.calls
        )
        if not deferred:
            # The model finished, but the operator queued more while it was working:
            # instead of ending the run, continue it with the queued text as the next
            # user request(s) — same run id, same stream, same usage/loop budget (so
            # a steady drip of messages still trips the turn's bounds rather than
            # extending them). `prompt=None` + a history ending in a user request is
            # the same continuation shape a regenerate uses.
            pending = run.drain_messages()
            if pending:
                message_history = messages + [
                    ModelRequest(parts=[UserPromptPart(m.text)]) for m in pending
                ]
                prompt = None
                deferred_results = None
                continue
            answer = output if isinstance(output, str) else None
            return _TurnResult(answer=answer, messages=messages)

        # Rule on each deferred *approval* — grants, then the level, then Auto's review.
        # The rules and their announcement live in `gating.py`; what is left here is what
        # the turn does with the two piles it hands back. Questions (`output.calls`) are
        # not put through any of it: a grant, a level and a reviewer all answer "may this
        # run", and a question is not asking that.
        settled, manual = await settle_deferred(
            run,
            output.approvals,
            caps=caps,
            conversation_id=conversation_id,
            deps=deps,
            messages=messages,
            permission=binding.permission,
        )
        if manual or output.calls:
            await park_for_input(
                run,
                agent,
                messages,
                output,
                announced,
                settled=settled,
                notifications=caps.get_optional(NotificationService),
                store=store,
                conversation_id=conversation_id,
                request_limit=request_limit,
                binding=binding,
                vision=vision,
                # Carried so a resume can recover from an overflow the way this turn would
                # have: the operator may take hours to answer, and the thread they come
                # back to is the one that was already near its ceiling.
                compaction=compaction,
            )
            return _TurnResult(answer=None, messages=messages)
        # Every deferred call settled without the operator — no question was asked, and
        # every approval was ruled on. Continue the SAME turn inline
        # (no round-trip), reusing the shared budget/guard/usage above. An auto-run tool
        # still streams its tool.started/completed, so it stays visible, and a call the
        # level refused comes back to the model as a denial it can plan around. Defensively
        # resolve any approval_needed notification still pending for this run — normally
        # a no-op (this branch only runs when nothing this hop parked), but idempotent
        # against whatever multi-hop history led here, so nothing is ever left dangling.
        notifications = caps.get_optional(NotificationService)
        if notifications is not None:
            with suppress(Exception):
                await notifications.resolve_for_run(run.owner_id, run.id)
        prompt = None
        message_history = messages
        deferred_results = DeferredToolResults(approvals=settled)


def _no_room_for(
    run: Run, messages: list[ModelMessage], nudge: str, *, threshold: float | None
) -> bool:
    """Whether replaying ``messages`` plus ``nudge`` would already be over the operator's
    share of the window. ``False`` whenever there is no window or no threshold to measure
    against — the same rule the compaction trigger follows, for the same reason."""
    if not run.context_window or not threshold or threshold <= 0:
        return False
    settings = get_settings()
    projected = estimate_footprint(
        messages,
        run.context_overhead,
        fallback_overhead_tokens=overhead_fallback_tokens(settings),
    ) + estimate_tokens([ModelRequest(parts=[UserPromptPart(content=nudge)])])
    return projected >= run.context_window * threshold


def _should_verify(settings: Any, run: Run) -> bool:
    """The verifier's heuristic trigger: judge only turns that produced a
    checkable artifact (made a tool call). Off ⇒ judge every answer."""
    if not settings.verify_heuristic:
        return True
    return bool(run.metrics and run.metrics.tool_calls)


async def _verify_and_correct(
    run: Run,
    agent: Agent,
    prompt: str,
    turn: _TurnResult,
    announced: set[str],
    judge: Judge,
    caps: ServiceContainer = _NO_CAPS,
    conversation_id: str | None = None,
    disabled_tools: frozenset[str] = frozenset(),
    partial_history_ref: list[Callable[[], list[ModelMessage]]] | None = None,
    store: ConversationStore | None = None,
    request_limit: int | None = None,
    binding: ConversationBinding = DEFAULT_BINDING,
    vision: bool = True,
    drop_ref: list[tuple[int, int]] | None = None,
    context_threshold: float | None = None,
) -> _TurnResult:
    """Judge the answer; on failure make a single bounded corrective re-attempt.

    A passing answer returns unchanged. Otherwise the correction's full history
    is returned with a ``clean_drop`` range that ``_finalize`` removes on persist
    (the rejected answer + the synthetic nudge), so the recorded history reads
    original request → corrected answer. If the correction itself parks for
    approval, the drop range rides on the parked payload so the resume cleans too;
    if it hits a bound, it is returned as-is (no premature persist, no lost answer).
    """
    if not turn.answer or not turn.answer.strip():
        return turn  # nothing checkable to verify
    verdict = await judge(prompt, turn.answer)
    if verdict.ok:
        return turn
    nudge = VERIFIER_NUDGE.format(reason=verdict.reason)
    # The correction is a *second* full pass over a history that has just finished its
    # first, so it runs at the turn's peak pressure — and it cannot fold, because its drop
    # range is a pair of absolute indices into this history. Attempting it against a
    # window that has no room left buys a context stop in place of an answer that, however
    # the judge scored it, is a real answer. Keep the answer and say what was skipped.
    if _no_room_for(run, turn.messages, nudge, threshold=context_threshold):
        run.emit(LimitNotice(limit="verify", message="skipped: no room for a re-attempt"))
        return turn
    run.emit(LimitNotice(limit="verify", message=f"re-attempting: {verdict.reason}"))
    # The range to drop on persist: the rejected ModelResponse (last message of
    # the original attempt) through the injected nudge ModelRequest (the first
    # new message of the correction) — two adjacent messages.
    clean_drop = (len(turn.messages) - 1, len(turn.messages))
    # Publish the range before re-driving, so a stop *during* the correction (an
    # inactivity bound, the operator's Stop) drops the same two messages the completed
    # path does. Without it, a stop here persists the rejected answer and a user message
    # nobody typed, and both replay to the model on every later turn.
    if drop_ref is not None:
        drop_ref[:] = [clean_drop]
    # One attempt only — no re-verify, so it cannot retry endlessly.
    corrected = await _drive_turn(
        run,
        agent,
        prompt=nudge,
        message_history=turn.messages,
        announced=announced,
        caps=caps,
        conversation_id=conversation_id,
        disabled_tools=disabled_tools,
        binding=binding,
        vision=vision,
        partial_history_ref=partial_history_ref,
        store=store,
        request_limit=request_limit,
        # No fold under a correction: `clean_drop` indexes the pre-fold history.
        correcting=True,
    )
    if run.status is RunStatus.awaiting_input:
        # The correction needs approval: carry the drop range on the parked turn
        # so the resume's persist drops the rejected answer + nudge as well.
        if isinstance(run.parked_payload, ParkedTurn):
            run.parked_payload.clean_drop = clean_drop
        return corrected
    if corrected.answer is None:
        # Hit a bound — the caller finalizes it, but the drop range has to ride along or
        # the rejected answer and the synthetic nudge persist as real transcript.
        return _TurnResult(
            answer=None,
            messages=corrected.messages,
            clean_drop=clean_drop,
            blocked_reason=corrected.blocked_reason,
        )
    return _TurnResult(answer=corrected.answer, messages=corrected.messages, clean_drop=clean_drop)


def _finalize(
    run: Run,
    turn: _TurnResult,
    *,
    store: ConversationStore | None,
    context: PersistContext,
) -> None:
    """Close out a turn: persist it, or wire resume context if it parked.

    Shared by the chat and resume orchestrators so the park/answer-None guards
    are applied *after* the verifier too (a corrective re-attempt can itself park
    or hit a bound). ``context`` is where the turn goes — see :class:`PersistContext`;
    its ``clean_drop`` is a verifier correction's message range to drop from the persisted
    history, and its ``attachment_ids``/``persisted`` carry a turn's attached files (the
    ids are stamped on the persisted request for chip rendering, and ``persisted`` is the
    durable content — the attachment markers, plus any retained image — that replaces the
    live payload in history)."""
    conversation_id = context.conversation_id
    if run.status is RunStatus.awaiting_input:
        # Parked: hand the resume the context to persist the parked turn too.
        if conversation_id is not None and isinstance(run.parked_payload, ParkedTurn):
            run.parked_payload.conversation_id = conversation_id
            run.parked_payload.persist_from = context.start
            if context.clean_drop is not None:  # re-park: carry the drop range forward
                run.parked_payload.clean_drop = context.clean_drop
            run.parked_payload.attachment_ids = list(context.attachment_ids)
            run.parked_payload.persisted = context.persisted
        return
    if turn.answer is None and not turn.blocked_reason:
        return  # hit a bound with nothing captured, or a cancel — nothing to persist
    if store is not None and conversation_id is not None:
        messages = turn.messages
        if context.clean_drop is not None:
            reject_idx, nudge_idx = context.clean_drop
            messages = messages[:reject_idx] + messages[nudge_idx + 1 :]
        # The store installs the durable `persisted` content and stamps `attachment_ids`
        # on the turn's user request as it serializes — what the durable blob contains is
        # the store's concern, not the engine's.
        # `blocked_reason` stamps the turn's branch node so a reload shows the same
        # persistent stop marker the live stream rendered (`record` is a no-op for an
        # empty slice, e.g. a bound hit before any new message accumulated).
        store.record(
            conversation_id,
            split_injected_requests(messages[context.start :]),
            attachment_ids=list(context.attachment_ids),
            persisted=context.persisted,
            blocked_reason=turn.blocked_reason,
            # The run's stopwatch, one entry per response it streamed, in the order the
            # store will meet them. Recorded on the same call as the messages so a
            # response and its duration can never be persisted apart.
            timings=run.timer.responses,
        )


def _flush_recorder(
    run: Run, store: ConversationStore | None
) -> Callable[[list[ModelMessage], str, PersistContext], None]:
    """The closure :class:`TurnFlush` records through — ``_finalize`` with this run's
    store already bound, so the flush module never has to know the engine's turn type."""

    def record(messages: list[ModelMessage], detail: str, context: PersistContext) -> None:
        _finalize(
            run,
            _TurnResult(answer=None, messages=messages, blocked_reason=detail),
            store=store,
            context=context,
        )

    return record


def _persist_parked_cancel(run: Run, *, store: ConversationStore | None) -> None:
    """Persist a parked turn's own messages when the operator cancels it while it is
    still awaiting an approval decision, instead of its resume-only persistence
    silently dropping the whole turn (the operator's own prompt included) — the
    parked counterpart of ``_on_cancel``'s flush for a still-running turn. Wired as
    ``run.on_park_cancel`` right after the parking ``_finalize`` call populates
    ``ParkedTurn``'s persistence context, so it's armed before any further ``await``
    a concurrent cancel could otherwise slip through (see ``park_for_input``'s
    identical notify-before-park ordering concern). Called by
    ``RunRegistry.cancel``'s parked branch *after* it has already set the terminal
    ``cancelled`` status, so ``_finalize`` takes its normal persist branch rather
    than its still-parked one."""
    parked = run.parked_payload
    if not isinstance(parked, ParkedTurn):
        return
    _flush_recorder(run, store)(parked.message_history, CANCELLED_DETAIL, _parked_context(parked))


def _parked_context(parked: ParkedTurn, start_ref: list[int] | None = None) -> PersistContext:
    """Where a parked turn goes — fixed at the moment it parked, so every path that
    persists it later (a resume's flush hooks, a cancel while still parked) agrees.

    ``start_ref`` is the live index a *running* resume holds: a fold during that resume
    rebuilds the history in front of the turn and moves it. A cancel of a still-parked run
    passes nothing, because nothing has folded — the payload's own index is the answer."""
    return PersistContext(
        conversation_id=parked.conversation_id,
        start=parked.persist_from if start_ref is None else start_ref[0],
        clean_drop=parked.clean_drop,
        attachment_ids=parked.attachment_ids,
        persisted=parked.persisted,
    )


def build_chat_orchestrator(
    prompt: str | None,
    *,
    model: Model,
    categories: Any = None,
    instruction_providers: Sequence[InstructionProvider] = (),
    prompt_context_providers: Sequence[PromptContextProvider] = (),
    judge: Judge | None = None,
    utility_model: Model | None = None,
    utility_settings: ModelSettings | None = None,
    title_model: Model | None = None,
    title_settings: ModelSettings | None = None,
    capabilities: ServiceContainer = _NO_CAPS,
    store: ConversationStore | None = None,
    conversation_id: str | None = None,
    context_window: int | None = None,
    context_thresholds: ContextThresholds = DEFAULT_CONTEXT_THRESHOLDS,
    uploads: UploadStore | None = None,
    attachment_ids: list[str] | None = None,
    vision: bool = False,
    auto_compact: AutoCompactPolicy | None = None,
    utility_context_window: int | None = None,
    disabled_tools: frozenset[str] = frozenset(),
    binding: ConversationBinding = DEFAULT_BINDING,
    request_limit: int | None = None,
) -> Orchestrator:
    """Build the orchestrator for one chat turn (one always-agent path).

    ``prompt`` is the operator's message, or ``None`` to **regenerate**: re-run
    from a history that already ends in the user request (the caller moved the
    active leaf there), producing a fresh answer as a sibling of the previous one.

    ``attachment_ids`` are files the operator attached to *this* message (resolved via
    ``uploads``). Their original bytes are staged into the conversation's sandbox and the
    turn carries a short marker naming each file and its path — the model reads and pages
    through the file itself rather than having its text poured into context. ``vision``
    additionally hands an image over as pixels, which is the one attachment kind that
    still rides inline (and is retained on persist). Attachments are injected only on a
    fresh turn; a regenerate (``prompt is None``) re-runs prior history, which already
    carries the markers.

    ``model`` is the resolved ``main`` model (the route resolves it from the
    registry, with any per-conversation override). ``categories`` overrides the
    tool catalog. The verifier's judge is ``judge`` if injected, else one built
    from ``utility_model`` when given; with neither, verification is skipped (a
    graceful degradation when no utility model is configured). ``utility_settings``
    carries that model's reasoning-off settings so the judge, like the namer, requests
    reasoning off. With ``store`` +
    ``conversation_id`` the turn continues prior history and persists its new
    messages; without them it runs stateless. The verifier only runs when enabled
    in settings (and, by default, only on tool-producing turns). With
    ``title_model`` (and ``title_enabled`` in settings) the *first* completed turn
    of a fresh thread is auto-named; ``title_settings`` carries the model's
    reasoning-off settings so the namer runs fast.

    ``request_limit`` is the turn's model-round-trip ceiling — the operator's setting
    when the caller resolved one, else the config default. It bounds the *whole* turn,
    grant-resume and mid-run-steering continuations included, so a steady drip of
    steering messages can't extend it.

    ``binding`` is the thread's workspace binding — its mode and its project — read off
    the conversation by the caller. It decides where this turn's file work happens
    (``services/workspace.py``) and, through ``disabled_tools``, which tools belong in it.

    A completed turn writes what its request weighed besides the conversation onto the
    thread (``ConversationStore.set_overhead``), so a later *reload* can still break the
    context down — a cold load has no request to measure, and neither the standing brief
    nor the tool schemas reach the message history.

    ``context_thresholds`` are the operator's severity boundaries for that window — the
    fullness at which the composer's gauge turns amber and then red. They only decide the
    ``level`` on the emitted metrics; nothing in the turn's behaviour keys off them.

    ``auto_compact`` is the conversation-compaction policy (the operator's default folded
    with any per-thread override; absent ⇒ the config defaults). When the replayed history
    *plus the turn about to run* would reach its share of ``context_window``, the turns
    before the retained tail are summarized onto a checkpoint before the agent runs, and
    the turn continues from that summary. The same fold is the recovery when a provider
    refuses an over-long request mid-turn. The summarizer is ``utility_model`` — the same
    cheap model the namer and the judge use — and ``utility_context_window`` is that
    model's own window, which bounds the transcript it is handed.
    """

    async def orchestrate(run: Run) -> None:
        settings = get_settings()
        run.context_window = context_window
        run.context_thresholds = context_thresholds
        agent = _build_agent(
            model, categories=categories, instruction_providers=instruction_providers
        )
        announced: set[str] = set()

        # --- the stop-flush hooks, armed before anything that can suspend -------------
        # Everything below this block awaits: the history read, auto-compaction (a whole
        # utility-model summarization, bounded by its own timeout), attachment resolution,
        # the per-turn context providers. None of it emits, so the inactivity watchdog is
        # ticking against a run that looks idle — and the compaction bound and the
        # inactivity bound share a default, so a compaction that runs to its own limit
        # trips the watchdog. Armed after that window, the hooks would be `None` exactly
        # when they are needed and the operator's typed message would vanish on reload.
        # The state they read is declared here and filled in below; a hook that fires
        # early simply sees the empty values, which is the correct record for a turn that
        # stopped before it began.
        # Where this turn's own messages begin in the replayed history. A one-element list
        # because an in-turn fold moves it: `_drive_turn` rewrites it in place, and every
        # reader below reads through it rather than closing over a stale integer.
        start_ref = [0]
        persisted: list | None = None
        stamp_ids: list[str] = []
        # Reachable mid-turn so a wall-clock/inactivity bound can flush whatever the
        # turn has produced before the registry force-cancels this task (which would
        # otherwise interrupt us before we reach `_finalize` below and silently drop
        # the turn on the next reload — see `RunRegistry._flush_timeout`).
        partial_history_ref: list[Callable[[], list[ModelMessage]]] = []

        def _turn_messages_or_prompt() -> list[ModelMessage]:
            # The turn's own messages — its slice of the partial history — or, if the
            # bound tripped in the pre-model setup window (before the first step landed
            # and `partial_history_ref` is still empty), the operator's typed prompt
            # alone. Without the fallback, a stop there would persist nothing and the
            # turn (the operator's own message) would vanish on reload. The plain
            # `prompt` persists, not the attachment/context-augmented `user_prompt`:
            # attachments ride on `persisted`/`stamp_ids` and per-turn context is
            # re-resolved fresh each turn and never persisted.
            if partial_history_ref:
                turn = partial_history_ref[0]()[start_ref[0] :]
                if turn:
                    return turn
            if isinstance(prompt, str) and prompt:
                return [ModelRequest(parts=[UserPromptPart(prompt)])]
            return []

        def _flush_context() -> PersistContext:
            # Read at flush time, not at arm time: `start_ref`, `stamp_ids` and `persisted`
            # are only known once the turn is under way, and the hooks are armed before
            # that (see above). `start=0` because `_turn_messages_or_prompt` hands over an
            # already-sliced list.
            return PersistContext(
                conversation_id=conversation_id,
                start=0,
                clean_drop=_flush_clean_drop(),
                attachment_ids=stamp_ids,
                persisted=persisted,
            )

        def _flush_clean_drop() -> tuple[int, int] | None:
            # A stop landing *during* a verifier correction must drop the same two
            # messages the completed path drops — the rejected answer and the synthetic
            # nudge the operator never sent — or they persist as real transcript and
            # replay to the model on every later turn. `drop_ref` carries the range in
            # absolute history indices; the hooks above hand `_finalize` an already
            # sliced list with `start=0`, so rebase it onto that slice.
            if not drop_ref:
                return None
            reject_idx, nudge_idx = drop_ref[0]
            start = start_ref[0]
            if reject_idx < start:
                return None
            return reject_idx - start, nudge_idx - start

        # Set by `_verify_and_correct` the moment it commits to a correction, so a stop
        # mid-correction can drop the same range the completed path does.
        drop_ref: list[tuple[int, int]] = []
        flush = TurnFlush(
            run,
            messages=_turn_messages_or_prompt,
            context=_flush_context,
            record=_flush_recorder(run, store),
        )
        flush.arm()
        # -----------------------------------------------------------------------------

        history = (
            await store.model_history(conversation_id)
            if store is not None and conversation_id is not None
            else None
        )
        # What the thread's earlier turns cost in wall-clock. Read once, here, because it
        # is the one part of the readout that isn't recoverable from the replayed history
        # — every count and token beside it is derived from the messages themselves. A
        # stateless turn has no thread to have spent anything, and keeps the zero default.
        if store is not None and conversation_id is not None:
            run.prior_timings = await store.timings(conversation_id)
            # What this thread's requests weighed besides the conversation, last time one
            # was assembled. Seeded onto the run so the trigger below and every frame
            # emitted before this turn's own measurement lands read the same overhead —
            # a gauge and a fold that disagreed about it would disagree about fullness.
            # `MeasureOverhead` replaces it with the live figure on the first request.
            run.context_overhead = await store.get_overhead(conversation_id)
        # What this turn may fold with. None ⇒ it cannot fold: a stateless run, or no
        # utility model to summarize with. The policy is resolved either way, because the
        # verifier's size guard measures against the same threshold on every turn.
        policy = auto_compact or build_auto_compact_policy(settings)
        compaction = (
            CompactionContext(
                store=store,
                conversation_id=conversation_id,
                policy=policy,
                model=utility_model,
                reasoning_off=utility_settings,
                settings=settings,
                max_input_tokens=resolve_max_input_tokens(settings, utility_context_window),
            )
            if store is not None and conversation_id is not None and utility_model is not None
            else None
        )
        # A fresh thread is the one that gets named, and that is settled by whether it had
        # any history at all — read before a fold could shorten it.
        is_first_turn = not history

        # Auto-title context for this run — None disables it (feature off, or no
        # utility model). Built up-front so the title can be generated *concurrently*
        # with the answer (it needs only the operator's opening message), leaving no
        # post-answer "writing" tail. Only a fresh thread's first turn is named.
        title_ctx = (
            TitleContext(title_model, title_settings or {})
            if title_model is not None and settings.title_enabled
            else None
        )
        title_namer = start_title(
            title_ctx if is_first_turn else None,
            prompt,
            run=run,
            store=store,
            conversation_id=conversation_id,
        )

        # Stage any attached files into this conversation's sandbox and append their
        # marker (name, id, mime, size, path) after the operator's prompt — the model
        # reads what it needs from the path rather than receiving the file's text. A
        # vision model additionally gets an image's pixels, the one kind that stays
        # inline in both the live and the persisted shape. Only on a fresh turn: a
        # regenerate (prompt is None) re-runs history, which already carries the markers.
        user_prompt: str | list[Any] | None = prompt
        if attachment_ids and prompt is not None and uploads is not None:
            resolved = await resolve_attachments(
                uploads,
                run.owner_id,
                attachment_ids,
                vision=vision,
                # Resolved the one way the file tools resolve it, so an attachment
                # lands in the very workspace the agent is about to work in — the
                # conversation's sandbox, or its project worktree in code mode.
                workspace=await resolve_workspace(
                    mode=binding.mode,
                    project_id=binding.project_id,
                    conversation_id=conversation_id,
                    sandbox_key=conversation_id or run.id,
                    owner_id=run.owner_id,
                    sessions=capabilities.get_optional(SandboxSessionManager),
                    projects=capabilities.get_optional(ProjectStore),
                    worktrees=capabilities.get_optional(WorktreeManager),
                    holder=run,
                ),
            )
            # Only build a multimodal prompt when something actually resolved — else leave
            # the plain string, so an all-deleted-ids turn doesn't persist as a bare list
            # (which the projection would read as empty text). Stamp only resolved ids as
            # chips; foreign/deleted ids are dropped.
            if resolved.content:
                user_prompt = [prompt, *resolved.content]
            persisted = resolved.persisted or None
            stamp_ids = resolved.ids

        # Per-turn prompt context (each manifest's `prompt_context` export — the
        # document state): appended at the *tail* of the current turn's user prompt,
        # never persisted, so it's re-resolved fresh each turn with exactly one copy
        # in context — and, unlike an instruction, its churn never touches the head
        # of the request, keeping the whole history a byte-stable cacheable prefix.
        #
        # Announced here rather than from the capability the head's blocks are read
        # from: these resolve before the agent starts, so there is no request to read
        # them back off. One event type either way — the operator's question is what
        # they were not shown, not which seam delivered it.
        context_texts: list[str] = []
        for provider in prompt_context_providers:
            text = await provider(capabilities, run.owner_id, conversation_id)
            if not text:
                continue
            context_texts.append(text)
            announce_injection(run, contributor_id(provider), text, "prompt")
        if context_texts:
            if prompt is not None:
                base = user_prompt if isinstance(user_prompt, list) else [user_prompt]
                user_prompt = [*base, *context_texts]
                # An empty (non-None) persisted set still strips the live payload back
                # to the typed prompt on record — the tail context must not persist.
                persisted = persisted if persisted is not None else []

        # Fold the older turns away — *after* the attachments and the per-turn context are
        # resolved, because they are part of what this turn will cost and the trigger is
        # projected: previous footprint + everything about to be added. Measuring the
        # history alone is what forced the old threshold up to 95%, since the incoming turn
        # had to fit in whatever the last one happened to leave spare.
        #
        # And *before* anything downstream measures the list: the rebuild has to land ahead
        # of both the dangling-call strip and `start_ref`, because that index is where
        # `_finalize` slices the turn out of `result.all_messages()` — it must count the
        # list actually handed to the model, not the one this started from.
        incoming = _incoming_request(user_prompt, context_texts if prompt is None else [])
        folded = False
        if history:
            history, folded = await _maybe_compact(
                run,
                compaction,
                history,
                overhead=run.context_overhead,
                incoming_tokens=estimate_tokens([incoming]) if incoming is not None else 0,
                context_window=context_window,
            )
        # A prior turn stopped at a bound persists its transcript verbatim — which can end on
        # an assistant tool call that never got its result. That full record is right for the
        # operator's view, but replaying a dangling tool call to the model is a provider error
        # (an assistant tool_call with no following tool result → HTTP 400), so strip it from
        # the *model's* input here. The persisted transcript is untouched; only this turn's
        # model history is sanitized, and `start_ref` tracks the trimmed length.
        if history:
            history = drop_dangling_tool_calls(history)
            history = merge_consecutive_requests(history)
        start_ref[0] = len(history) if history else 0
        if folded:
            # Every response left in the replay reported its prompt size against the
            # history that was just folded away, so none of them describes the thread as it
            # now stands. Marking the whole replay pre-fold makes the frame below read the
            # estimate instead — which is the point of emitting one at all: the operator
            # asked for a fold and must see the gauge fall, not sit at its old figure until
            # the answer lands.
            run.fold_boundary = start_ref[0]
            run.emit(_turn_metrics(run, history or []))
        # What the model replays — `history` plus, on a regenerate, the per-turn prompt
        # context. `history` itself stays the persistence baseline.
        model_history = history
        if context_texts and prompt is None and history:
            # A regenerate has no fresh prompt — the context rides on the trailing
            # user request in the *model's* view only (`history` itself stays
            # pristine for the verifier's `last_user_text`, and everything before
            # `start_ref` is never re-persisted).
            model_history = with_tail_context(history, context_texts)

        try:
            turn = await _drive_turn(
                run,
                agent,
                prompt=user_prompt,
                message_history=model_history,
                announced=announced,
                caps=capabilities,
                conversation_id=conversation_id,
                disabled_tools=disabled_tools,
                binding=binding,
                vision=vision,
                partial_history_ref=partial_history_ref,
                store=store,
                request_limit=request_limit,
                compaction=compaction,
                start_ref=start_ref,
            )

            # Verify only a completed turn (not one parked for approval or stopped at
            # a bound), and only when the heuristic says it is worth judging.
            if (
                run.status is not RunStatus.awaiting_input
                and turn.answer is not None
                and settings.verify_enabled
                and _should_verify(settings, run)
            ):
                judging = judge or (
                    make_utility_judge(utility_model, model_settings=utility_settings)
                    if utility_model
                    else None
                )
                if judging is not None:  # no judge and no utility model → skip (degraded)
                    # On a regenerate (prompt is None) the request to judge against is
                    # the last user turn already in history.
                    verify_prompt = prompt if prompt is not None else last_user_text(history or [])
                    turn = await _verify_and_correct(
                        run,
                        agent,
                        verify_prompt,
                        turn,
                        announced,
                        judging,
                        caps=capabilities,
                        conversation_id=conversation_id,
                        disabled_tools=disabled_tools,
                        binding=binding,
                        vision=vision,
                        partial_history_ref=partial_history_ref,
                        store=store,
                        request_limit=request_limit,
                        drop_ref=drop_ref,
                        # The correction cannot fold, so it is skipped outright when the
                        # window has no room left for it. Measured against the same share
                        # of the window a fold would have fired at, whether or not this
                        # turn is one that *could* fold.
                        context_threshold=policy.threshold,
                    )

            _finalize(
                run,
                turn,
                store=store,
                # The completed path measures against the real `start_ref` — which an
                # in-turn fold may have moved — and carries the verifier's own drop range,
                # where a flush hands over an already-sliced list; hence its own context
                # rather than `_flush_context()`.
                context=PersistContext(
                    conversation_id=conversation_id,
                    start=start_ref[0],
                    clean_drop=turn.clean_drop,
                    attachment_ids=stamp_ids,
                    persisted=persisted,
                ),
            )
            # Disarm the flush hooks now the turn is recorded: a wall-clock/inactivity bound
            # or a cancel landing during the post-answer title window (below) must not
            # re-run `_finalize` and double-record the turn (or stamp a spurious stop on a
            # completed answer).
            flush.disarm()
            flush.done = True

            if run.status is RunStatus.awaiting_input:
                # Arm the park-cancel flush now, before any further `await` — a
                # concurrent cancel of this now-externally-visible parked run must
                # find `ParkedTurn`'s persistence context already wired (see
                # `_persist_parked_cancel`'s docstring for why this can't wait until
                # after `_discard_title`'s own await below).
                run.on_park_cancel = lambda: _persist_parked_cancel(run, store=store)
                # Parked for approval before producing an answer: abandon the concurrent
                # namer so its *model call* doesn't outlive the run, and carry the context
                # forward so the resume names the thread if this cancel got there first
                # (the resume titles from history). A namer far enough along to have begun
                # announcing finishes regardless — a thread waiting on an approval shows
                # its name rather than sitting "Untitled" for however long the operator
                # takes to decide — and the resume's `set_title_if_absent` then finds the
                # name in place, returns False, and emits nothing a second time.
                await discard_title(title_namer)
                if isinstance(run.parked_payload, ParkedTurn):
                    run.parked_payload.title = title_ctx
            else:
                # The namer started up-front announces itself the moment the name lands
                # (typically well before the answer does); this only waits for a still-
                # running one so the event is emitted before the orchestrator returns
                # (run.ended) and the open stream carries it.
                await settle_title(title_namer)

            # What this turn's requests weighed besides the conversation, written onto
            # the thread for its own next cold load — neither the brief nor the schemas
            # reach the message history, so this is the only way a reopened conversation
            # can break its footprint down instead of reporting one flat figure.
            #
            # **Last, and never fatal.** It sits here rather than beside `_drive_turn`
            # for three reasons, each of which the earlier placement got wrong: it must
            # follow the verifier, whose corrective re-attempt drives further requests
            # and leaves a newer measurement behind; it must follow `_finalize`, so a
            # thread never carries overhead for a turn whose messages didn't record; and
            # it must not `await` between a park and the `on_park_cancel` arming above,
            # which a concurrent cancel of the now-visible parked run depends on. The
            # write is swallowed because this is a readout: losing the breakdown costs a
            # reload its detail, where letting the failure out would turn an answered
            # turn into an errored run and route its messages through the degraded
            # error-flush instead of the finalize that already recorded them.
            if store is not None and conversation_id is not None:
                try:
                    await store.set_overhead(conversation_id, run.context_overhead)
                except Exception:
                    logger.warning("failed to record context overhead", exc_info=True)
        except Exception:
            # Anything else that escapes `_drive_turn` (a provider error its specific
            # catches don't cover, a tool/dependency raising, …) must still not silently
            # drop the operator's own prompt: persist whatever the turn had produced,
            # carrying a legible marker, before this propagates to the registry's own
            # generic handler, which records the run as `error`. Mirrors the
            # timeout/cancel flush above but never touches `run.status` — the registry
            # is the one that decides the terminal outcome for an unhandled exception.
            # It flushes through `_turn_messages_or_prompt` rather than the raw partial
            # history, for the same reason the two hook paths do: an exception raised
            # before the first step landed leaves `partial_history_ref` empty, and
            # persisting that empty slice drops the operator's own typed prompt exactly
            # the way a bound tripping in the prelude used to.
            flush.flush_error()
            # Disarm now that this path has (or the normal path already did) recorded
            # the turn — the task is unwinding, so no further hook call is legitimate.
            flush.disarm()
            raise
        finally:
            # Safety net: if the turn raised or was cancelled before the title was
            # consumed above, don't let the detached title-model call outlive the run.
            if title_namer is not None and not title_namer.task.done():
                if not title_namer.announcing.is_set():
                    # Still waiting on the title model — nothing committed yet, so a
                    # bare cancel is safe and this path is unwinding anyway.
                    title_namer.task.cancel()
                else:
                    # Past `announcing` there is no model call left to abandon, only the
                    # write and the emit, which must not be split. Left detached, it
                    # would race the stream close in `RunRegistry._run`'s finally and
                    # lose `conversation.titled` — the name reaching the database but
                    # never the client. Shielded so an unwinding *cancellation* still
                    # leaves the task alive to finish its write; on that path the await
                    # itself aborts and the event is genuinely lost, which is the
                    # accepted cost of a Stop landing in this exact window (the title is
                    # in the database and appears on reload). On the error path — not
                    # cancelled — the await completes and the frame rides the open
                    # stream as it should.
                    with suppress(Exception, asyncio.CancelledError):
                        await asyncio.shield(title_namer.task)

    return orchestrate


def build_resume_orchestrator(
    parked: ParkedTurn,
    decisions: dict[str, Any],
    *,
    answers: dict[str, str] | None = None,
    capabilities: ServiceContainer = _NO_CAPS,
    store: ConversationStore | None = None,
    disabled_tools: frozenset[str] = frozenset(),
) -> Orchestrator:
    """Resume a parked turn with the operator's approve/deny decisions and answers.

    Both piles in one resume, because the park was one park: a turn that stopped on an
    approval *and* a question has a single continuation, and starting it twice would run
    the second against a history the first had already moved past.
    """

    async def orchestrate(run: Run) -> None:
        # `calls` carries values rather than verdicts — Pydantic AI wraps each one in a
        # `ToolReturn`, so the operator's answer lands in history as that call's own
        # result and the model reads it exactly as it would any other tool's.
        results = DeferredToolResults(approvals=decisions, calls=answers or {})

        # Same reasoning as the chat orchestrator's `_on_timeout`: a resumed turn is
        # bound by fresh wall-clock/inactivity timeouts too (see `RunRegistry.resume`),
        # so it needs the same flush-before-force-cancel hook.
        partial_history_ref: list[Callable[[], list[ModelMessage]]] = []
        # Unlike a chat turn, a resume's destination is already settled — it rode here on
        # the `ParkedTurn` — so only the messages move, and the one index that can still
        # move with them is the persistence start: an overflow recovery folds the thread
        # underneath this turn and rebuilds the history in front of it.
        start_ref = [parked.persist_from]
        flush = TurnFlush(
            run,
            messages=lambda: partial_history_ref[0]() if partial_history_ref else [],
            context=lambda: _parked_context(parked, start_ref),
            record=_flush_recorder(run, store),
        )
        flush.arm()
        try:
            turn = await _drive_turn(
                run,
                parked.agent,
                message_history=parked.message_history,
                deferred_results=results,
                announced=parked.announced,
                caps=capabilities,
                conversation_id=parked.conversation_id,
                # The route re-reads the operator/offline/mode sources so a tool switched
                # off while this was parked stays hidden; the vision half comes off the
                # payload instead, because only the parked agent knows which model it
                # holds (see `ParkedTurn.vision`).
                disabled_tools=disabled_tools | vision_disabled_tools(parked.vision),
                # From the parked payload, not a fresh read: the resumed turn must work
                # in the same place the parked one did.
                binding=parked.binding,
                partial_history_ref=partial_history_ref,
                store=store,
                # The ceiling the parked turn was running under — a resume continues
                # under the same one rather than reverting to the config default.
                request_limit=parked.request_limit,
                # And what it may fold with, so a resume that overruns the window recovers
                # exactly as the original turn would have. A turn that parked *inside* a
                # verifier correction carries a drop range indexed into the pre-fold
                # history, so it is barred from folding for the same reason the correction
                # itself was.
                compaction=parked.compaction,
                start_ref=start_ref,
                correcting=parked.clean_drop is not None,
            )
            _finalize(run, turn, store=store, context=_parked_context(parked, start_ref))
            # Disarm the flush hooks now the turn is recorded — a bound or cancel
            # landing during the title window below must not re-finalize (see the
            # chat orchestrator).
            flush.disarm()
            flush.done = True

            if run.status is RunStatus.awaiting_input:
                # Re-parked on a further approval: re-arm the park-cancel flush (see
                # the chat orchestrator's identical wiring) and carry the title
                # context forward to the new parked payload so the eventual
                # completion still names it.
                run.on_park_cancel = lambda: _persist_parked_cancel(run, store=store)
                if isinstance(run.parked_payload, ParkedTurn):
                    run.parked_payload.title = parked.title
            else:
                # A first turn that parked then resumed to completion is still the
                # opening exchange — name it (persist_from == 0 means no prior turns).
                await maybe_title(
                    run,
                    title=parked.title,
                    store=store,
                    conversation_id=parked.conversation_id,
                    is_first_turn=parked.persist_from == 0,
                )
        except Exception:
            # Same reasoning as the chat orchestrator's identical clause: an
            # unhandled exception must not silently drop this turn (which, on a
            # resume, includes everything since the original park) from persistence.
            flush.flush_error()
            # Disarm now that this path has (or the normal path already did) recorded
            # the turn — the task is unwinding, so no further hook call is legitimate.
            flush.disarm()
            raise

    return orchestrate
