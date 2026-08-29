"""The agent engine — the first real orchestrator on the Run substrate.

Wraps Pydantic AI's ``Agent`` and drives it via ``agent.iter()`` so the chassis
can observe every step and stream it (translation lives in ``translate.py``).
The library owns the within-turn loop, tool selection, validation, and fallback;
we own the run lifecycle, the event stream, bounds, and the approval pause/resume
for sensitive actions. The meta-loop (verifier/loop-break) lands here next.

A turn is driven by :func:`_drive_turn`, shared by the initial run and every
approval resume. When the model requests a sensitive (approval-required) tool,
Pydantic AI ends the turn with ``DeferredToolRequests`` *without executing it*;
we surface ``approval.required``, park the Run (``awaiting_input``), and stash a
:class:`ParkedTurn` so an approve decision can resume exactly where it left off.

What lives *here* is the turn's control flow and the two orchestrators that wrap it.
Four neighbours carry the concerns that aren't that, each with its own reason to change:

- ``history.py`` — the surgeries on a message list before it reaches a model or the
  store. Pure functions; each encodes one fact about how the library or a provider
  behaves.
- ``naming.py`` — when and how a fresh thread gets named, either concurrently with the
  answer or after a resume. (``title.py`` remains the model call itself.)
- ``flush.py`` — persisting a turn that was stopped from outside, shared by both
  orchestrators so a bound, a cancel and an unhandled exception cannot drift apart.
- ``model_errors.py`` — reading a provider's failure: which stop it is, and what the
  operator is told.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from functools import wraps
from inspect import isawaitable
from typing import Any

from pydantic_ai import (
    Agent,
    DeferredToolRequests,
    DeferredToolResults,
    ModelMessage,
    ModelRequest,
    RunContext,
    RunUsage,
    ToolApproved,
    UsageLimitExceeded,
    UsageLimits,
    UserPromptPart,
)
from pydantic_ai.capabilities import ReinjectSystemPrompt
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings

from core.config import Settings, get_settings
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
    ApprovalRequired,
    ContextThresholds,
    ConversationCompacted,
    LimitNotice,
    Orchestrator,
    Run,
    RunMetrics,
    RunStatus,
    total_timings,
)
from services.approval_grants import ApprovalGrantStore, covered_by_grant
from services.context_budget import OverheadCache, compose
from services.conversations import (
    ConversationBinding,
    ConversationStore,
    context_footprint,
    conversation_totals,
)
from services.notifications import NotificationService
from services.projects import ProjectStore, WorktreeManager
from services.sandbox import SandboxSessionManager
from services.uploads import UploadStore
from services.workspace import resolve_workspace
from tools import (
    InstructionProvider,
    PromptContextProvider,
    RunDeps,
    build_agent_toolsets,
)

from .attachments import resolve_attachments
from .flush import CANCELLED_DETAIL, PersistContext, TurnFlush
from .history import (
    drop_dangling_tool_calls,
    merge_consecutive_requests,
    split_injected_requests,
    with_tail_context,
)
from .meta import Judge, LoopBreaker, LoopDetected, make_utility_judge
from .model_errors import (
    context_limit_message,
    is_context_overflow,
    model_load_hint,
    usage_limit_kind,
    usage_limit_message,
)
from .naming import (
    TitleContext,
    approval_conversation_title,
    discard_title,
    maybe_title,
    settle_title,
    start_title,
)
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
# A stateless turn's workspace binding: an unfiled chat thread. The conservative default —
# chat mode never reaches the host — so a caller that forgets to resolve one cannot
# accidentally hand a run the operator's own files.
_CHAT_BINDING = ConversationBinding()


@dataclass
class ParkedTurn:
    """The continuation of a run parked awaiting approval. Opaque to the
    substrate; held on ``run.parked_payload`` and consumed by the approve route."""

    agent: Agent
    message_history: list[ModelMessage]
    requests: DeferredToolRequests
    announced: set[str] = field(default_factory=set)
    # Calls already auto-approved by an active conversation grant — surfaced to the
    # operator (no approval.required event for them) but merged back into the resume's
    # decisions so the single DeferredToolResults still covers every deferred call.
    pre_approved: dict[str, ToolApproved] = field(default_factory=dict)
    # Persistence context, attached by the orchestrator: the conversation and
    # the index from which messages are still unpersisted (so a resume records
    # the parked turn's messages too, once it finally completes).
    conversation_id: str | None = None
    persist_from: int = 0
    # When a *verifier* correction is what parked, the [start, end] message range
    # to drop on the eventual persist (the rejected answer + the synthetic nudge),
    # so the resume records a clean history too.
    clean_drop: tuple[int, int] | None = None
    # Auto-title context, carried so a first turn that parked for approval is still
    # named once it resumes and completes (titling lives at the shared finalize
    # point, not only in the initial chat turn). None ⇒ don't title on resume.
    title: TitleContext | None = None
    # Attachment context, carried so a turn that parked for approval still installs its
    # durable attachment markers (and stamps the ids) when the resume finally persists it —
    # keeping replayed history marker-only just like a direct turn.
    attachment_ids: list[str] = field(default_factory=list)
    persisted: list | None = None
    # The turn's model-request budget (the operator's setting, else the config default),
    # carried so the resume continues under the same ceiling the original turn ran with
    # rather than silently reverting to the default. None ⇒ resolve from config.
    request_limit: int | None = None
    # The thread's workspace binding, carried rather than re-read on resume. It is
    # immutable for the life of a conversation, so re-resolving it would be a second
    # source for one fact — and a resume that defaulted it to chat would hand a parked
    # coding turn a different filesystem than the one it parked in.
    binding: ConversationBinding = field(default_factory=ConversationBinding)


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
        output_type=[str, DeferredToolRequests],
        # ReinjectSystemPrompt keeps our system prompt authoritative — it transforms only
        # what the model sees, never what we persist. Nothing else rewrites the history on
        # its way to the model: a tool result rides into context whole, and the one
        # reduction that exists (conversation compaction) fires between turns, in the
        # orchestrator prelude, against measured context pressure.
        capabilities=[ReinjectSystemPrompt(replace_existing=True)],
    )

    # Feature-contributed dynamic instructions (each manifest's `instructions` export —
    # the skill catalog): re-resolved fresh each turn, so they're always current and,
    # unlike an appended prompt, never accumulate in history. Each resolves its own
    # capability from the run's bag and no-ops (returns "") when the capability isn't
    # wired, so registration is unconditional. Instructions render at the *head* of
    # every request — keep them small and low-churn, or they invalidate the inference
    # engine's prompt-prefix cache for the whole history behind them (volatile context
    # belongs in a manifest's `prompt_context` export instead, delivered at the tail).
    for provider in instruction_providers:
        agent.instructions(_attributed(provider))

    @agent.instructions
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


def _attributed(provider: InstructionProvider) -> InstructionProvider:
    """Wrap an instruction provider so the brief it contributes can be attributed to it.

    The context readout breaks the standing brief down by which feature put text there —
    the one form of the figure an operator can act on, since each block corresponds to
    something they can switch off. That attribution is only available *here*: the library
    concatenates every provider's return value into one instructions string, and by the
    time the request exists there is no seam left to cut on. So each provider's own
    output is measured as it is produced and left on the Run for `agent/overhead.py` to
    read at the end of the step.

    Records characters, never the text: this is a gauge annotation, and a copy of the
    brief on the Run would be one more place a prompt lives.
    """
    block = _block_id(provider)

    @wraps(provider)
    async def attributed(ctx: RunContext[RunDeps]) -> str:
        # Awaited only when there is something to await: `InstructionProvider` describes
        # the async shape, but the library accepts a plain sync function and features
        # write them, so a blanket `await` here would break every synchronous provider's
        # turn for the sake of a readout row.
        produced = provider(ctx)
        text = await produced if isawaitable(produced) else produced
        # Defensive on both hops: an agent built without deps (a test harness) and a
        # provider that returned a non-string both cost the block's row, not the turn.
        run = getattr(getattr(ctx, "deps", None), "run", None)
        if run is not None and isinstance(text, str):
            run.instruction_blocks[block] = len(text)
        return text

    return attributed


def _block_id(provider: InstructionProvider) -> str:
    """The slug a provider's contribution is filed under — its own name, minus the
    `_instructions` suffix the convention gives them (`skill_catalog_instructions` →
    `skill_catalog`).

    Derived rather than declared because `InstructionProvider` is a plain callable and
    giving every manifest a label field would be ceremony for a readout row. A rename
    therefore renames the row, which is the honest failure: the client de-slugs whatever
    it is given, so the worst case is a row reading "Skill catalog" instead of "Skills"
    — never a wrong number.
    """
    name = getattr(provider, "__name__", "") or "instructions"
    return name.strip("_").removesuffix("_instructions").removeprefix("instructions_") or "base"


def _summarize(name: str, args: dict[str, Any]) -> str:
    rendered = ", ".join(f"{k}={v!r}" for k, v in args.items())
    return f"{name}({rendered})"


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
    metrics never diverge."""
    counts = conversation_totals(messages)
    timings = run.prior_timings + total_timings(run.timer.responses)
    footprint = context_footprint(messages)
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
    )


async def _maybe_compact(
    run: Run,
    store: ConversationStore,
    conversation_id: str,
    history: list[ModelMessage],
    *,
    policy: AutoCompactPolicy,
    model: Model | None,
    reasoning_off: ModelSettings | None,
    context_window: int | None,
    settings: Settings,
) -> list[ModelMessage]:
    """Fold this conversation's older turns into a summary when it has reached the
    operator's share of the model's context window, returning the history to replay.

    Returns ``history`` unchanged whenever compaction is off, unmeasurable (no declared
    window), not yet due, has nothing left to fold, or the summarizer failed — this runs on
    the critical path of every turn, so nothing here may raise. Compaction is an efficiency
    measure, not a guard: when it doesn't free enough room the turn still meets the model's
    real ceiling and stops with the context notice, which is the honest outcome.

    Emitted before the answer streams, so the operator sees *why* the thread's memory
    changed shape at the moment it happens rather than inferring it from a shorter reply."""
    if not policy.enabled or model is None:
        return history
    if not should_compact(history, context_window, policy.threshold):
        return history
    try:
        outcome = await compact_conversation(
            store,
            conversation_id,
            model=model,
            reasoning_off=reasoning_off,
            keep_turns=policy.keep_turns,
            settings=settings,
        )
    except Exception:  # noqa: BLE001 — an optimization must never take the turn down with it
        logger.warning("auto-compaction failed for %s", conversation_id, exc_info=True)
        return history
    if outcome is None:
        return history
    run.emit(
        ConversationCompacted(
            conversation_id=conversation_id,
            message_id=outcome.message_id,
            summary=outcome.summary,
            messages_compacted=outcome.messages_compacted,
            tokens_before=outcome.tokens_before,
            tokens_after=outcome.tokens_after,
            after_message_id=outcome.after_message_id,
        )
    )
    return await store.model_history(conversation_id)


async def _park_for_approval(
    run: Run,
    agent: Agent,
    messages: list[ModelMessage],
    requests: DeferredToolRequests,
    announced: set[str],
    *,
    pre_approved: dict[str, ToolApproved] | None = None,
    notifications: NotificationService | None = None,
    store: ConversationStore | None = None,
    conversation_id: str | None = None,
    request_limit: int | None = None,
    binding: ConversationBinding = _CHAT_BINDING,
) -> None:
    # Only the calls still awaiting the operator are announced; any pre-approved by an
    # active grant ride silently on the parked payload and merge into the resume.
    pre_approved = pre_approved or {}
    pending_names: set[str] = set()
    for call in requests.approvals:
        if call.tool_call_id in pre_approved:
            continue
        pending_names.add(call.tool_name)
        args = call.args_as_dict()
        # A tool may hand the operator a plain-language explanation via an
        # `explanation` argument (the host-execution path requires one); surface
        # it as a distinct field so the client need not parse it out of the args.
        explanation = args.get("explanation")
        run.emit(
            ApprovalRequired(
                tool_call_id=call.tool_call_id,
                name=call.tool_name,
                args=args,
                summary=_summarize(call.tool_name, args),
                explanation=explanation if isinstance(explanation, str) else None,
            )
        )
    # Fire the ALWAYS-notify policy *before* `run.park(...)` makes the parked status
    # externally visible — not after. This is the one await this function does before
    # parking, and it must land first: `RunRegistry.cancel`'s parked branch assumes
    # "awaiting_input ⇒ the task has already fully exited" and skips the hard-cancel
    # path on that assumption. If the notify (and the conversation-title lookup it may
    # need) instead ran *after* parking, a concurrent cancel/approve landing in that
    # window would see the parked status while this coroutine is still suspended on a
    # real await — violating that assumption and racing the run's own finalize.
    if notifications is not None and pending_names:
        title = await approval_conversation_title(store, run.owner_id, conversation_id)
        try:
            await notifications.notify(
                run.owner_id,
                "approval_needed",
                f'"{title}" needs approval for {", ".join(sorted(pending_names))}',
                conversation_id=conversation_id,
                run_id=run.id,
            )
        except Exception:  # noqa: BLE001 — a notify failure must not break the park
            logger.warning("approval_needed notification failed for run %s", run.id, exc_info=True)
    run.park(
        ParkedTurn(
            agent,
            messages,
            requests,
            announced,
            pre_approved=pre_approved,
            request_limit=request_limit,
            binding=binding,
        )
    )


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
    binding: ConversationBinding = _CHAT_BINDING,
    partial_history_ref: list[Callable[[], list[ModelMessage]]] | None = None,
    store: ConversationStore | None = None,
    request_limit: int | None = None,
) -> _TurnResult:
    settings = get_settings()
    # ``request_limit`` is the operator's runtime setting when the caller resolved one;
    # absent (a stateless/eval turn, or an older parked payload) it falls back to the
    # config default. It bounds *model round-trips*, so every tool call spends one.
    limits = UsageLimits(
        request_limit=(settings.agent_request_limit if request_limit is None else request_limit),
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
            # Context-window overflow: a definitive ceiling, not something to paper over by
            # silently dropping content — stop and tell the operator the model's limit so they
            # can start a new chat or trim. (Compaction reduces pressure; it never absorbs this.)
            if is_context_overflow(exc):
                run.emit(LimitNotice(limit="context", message=context_limit_message(run)))
                detail = "context window exceeded"
                run.block(detail)
                return _TurnResult(
                    answer=None,
                    messages=_partial_history(),
                    blocked_reason=detail,
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
        if not (isinstance(output, DeferredToolRequests) and output.approvals):
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

        # A tool the operator allowed for this conversation auto-approves without a
        # prompt; the rest still park for a decision. Grants are conversation-scoped,
        # so a stateless (no-conversation) turn always asks.
        granted: set[str] = set()
        grants = caps.get_optional(ApprovalGrantStore)
        if grants is not None and conversation_id is not None:
            granted = await grants.active(run.owner_id, conversation_id)
        pre_approved = {
            call.tool_call_id: ToolApproved()
            for call in output.approvals
            if covered_by_grant(call.tool_name, granted)
        }
        manual = [c for c in output.approvals if c.tool_call_id not in pre_approved]
        if manual:
            await _park_for_approval(
                run,
                agent,
                messages,
                output,
                announced,
                pre_approved=pre_approved,
                notifications=caps.get_optional(NotificationService),
                store=store,
                conversation_id=conversation_id,
                request_limit=request_limit,
                binding=binding,
            )
            return _TurnResult(answer=None, messages=messages)
        # Every deferred call is grant-covered — continue the SAME turn inline (no
        # operator round-trip), reusing the shared budget/guard/usage above. The auto-run
        # tool still streams its tool.started/completed, so it stays visible. Defensively
        # resolve any approval_needed notification still pending for this run — normally
        # a no-op (this branch only runs when nothing this hop parked), but idempotent
        # against whatever multi-hop history led here, so nothing is ever left dangling.
        notifications = caps.get_optional(NotificationService)
        if notifications is not None:
            with suppress(Exception):
                await notifications.resolve_for_run(run.owner_id, run.id)
        prompt = None
        message_history = messages
        deferred_results = DeferredToolResults(approvals=pre_approved)


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
    binding: ConversationBinding = _CHAT_BINDING,
    drop_ref: list[tuple[int, int]] | None = None,
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
    run.emit(LimitNotice(limit="verify", message=f"re-attempting: {verdict.reason}"))
    nudge = VERIFIER_NUDGE.format(reason=verdict.reason)
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
        partial_history_ref=partial_history_ref,
        store=store,
        request_limit=request_limit,
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
    a concurrent cancel could otherwise slip through (see ``_park_for_approval``'s
    identical notify-before-park ordering concern). Called by
    ``RunRegistry.cancel``'s parked branch *after* it has already set the terminal
    ``cancelled`` status, so ``_finalize`` takes its normal persist branch rather
    than its still-parked one."""
    parked = run.parked_payload
    if not isinstance(parked, ParkedTurn):
        return
    _flush_recorder(run, store)(parked.message_history, CANCELLED_DETAIL, _parked_context(parked))


def _parked_context(parked: ParkedTurn) -> PersistContext:
    """Where a parked turn goes — fixed at the moment it parked, so every path that
    persists it later (a resume's flush hooks, a cancel while still parked) agrees."""
    return PersistContext(
        conversation_id=parked.conversation_id,
        start=parked.persist_from,
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
    disabled_tools: frozenset[str] = frozenset(),
    binding: ConversationBinding = _CHAT_BINDING,
    request_limit: int | None = None,
    overhead_cache: OverheadCache | None = None,
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

    ``overhead_cache`` remembers what this turn's request weighed besides the
    conversation, so a *reload* of the thread can still show the context breakdown — a
    cold load has no request to measure. See ``services.context_budget.OverheadCache``
    for why that is remembered rather than stored.

    ``context_thresholds`` are the operator's severity boundaries for that window — the
    fullness at which the composer's gauge turns amber and then red. They only decide the
    ``level`` on the emitted metrics; nothing in the turn's behaviour keys off them.

    ``auto_compact`` is the conversation-compaction policy (the operator's default folded
    with any per-thread override; absent ⇒ the config defaults). When the replayed history
    has reached its share of ``context_window``, the turns before the retained tail are
    summarized onto a checkpoint *before* the agent runs, and the turn continues from that
    summary. The summarizer is ``utility_model`` — the same cheap model the namer and the
    judge use.
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
        start = 0
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
                turn = partial_history_ref[0]()[start:]
                if turn:
                    return turn
            if isinstance(prompt, str) and prompt:
                return [ModelRequest(parts=[UserPromptPart(prompt)])]
            return []

        def _flush_context() -> PersistContext:
            # Read at flush time, not at arm time: `start`, `stamp_ids` and `persisted`
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
        # Fold the older turns away *before* anything downstream measures this list. The
        # rebuild has to land ahead of both `_drop_dangling_tool_calls` and `start`, because
        # `start` is the index `_finalize` slices the turn out of `result.all_messages()` at
        # — it must count the list actually handed to the model, not the one we started from.
        if history and store is not None and conversation_id is not None:
            history = await _maybe_compact(
                run,
                store,
                conversation_id,
                history,
                policy=auto_compact or build_auto_compact_policy(settings),
                model=utility_model,
                reasoning_off=utility_settings,
                context_window=context_window,
                settings=settings,
            )
        # A prior turn stopped at a bound persists its transcript verbatim — which can end on
        # an assistant tool call that never got its result. That full record is right for the
        # operator's view, but replaying a dangling tool call to the model is a provider error
        # (an assistant tool_call with no following tool result → HTTP 400), so strip it from
        # the *model's* input here. The persisted transcript is untouched; only this turn's
        # model history is sanitized, and `start` tracks the trimmed length.
        if history:
            history = drop_dangling_tool_calls(history)
            history = merge_consecutive_requests(history)
        start = len(history) if history else 0
        is_first_turn = start == 0
        # What the model replays — `history` plus, on a regenerate, the per-turn prompt
        # context appended below. `history` itself stays the persistence baseline.
        model_history = history

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
                # conversation's sandbox, or its project worktree in coding mode.
                workspace=await resolve_workspace(
                    mode=binding.mode,
                    project_id=binding.project_id,
                    conversation_id=conversation_id,
                    sandbox_key=conversation_id or run.id,
                    owner_id=run.owner_id,
                    sessions=capabilities.get_optional(SandboxSessionManager),
                    projects=capabilities.get_optional(ProjectStore),
                    worktrees=capabilities.get_optional(WorktreeManager),
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
        context_texts = [
            text
            for provider in prompt_context_providers
            if (text := await provider(capabilities, run.owner_id, conversation_id))
        ]
        if context_texts:
            if prompt is not None:
                base = user_prompt if isinstance(user_prompt, list) else [user_prompt]
                user_prompt = [*base, *context_texts]
                # An empty (non-None) persisted set still strips the live payload back
                # to the typed prompt on record — the tail context must not persist.
                persisted = persisted if persisted is not None else []
            elif history:
                # A regenerate has no fresh prompt — the context rides on the trailing
                # user request in the *model's* view only (`history` itself stays
                # pristine for the verifier's `last_user_text`, and everything before
                # `start` is never re-persisted).
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
                partial_history_ref=partial_history_ref,
                store=store,
                request_limit=request_limit,
            )
            # What this turn's requests weighed besides the conversation, kept for the
            # next cold load of any thread in this mode. Recorded here rather than where
            # it is measured because the mode is what keys it, and the mode is the
            # orchestrator's to know.
            if overhead_cache is not None:
                overhead_cache.remember(binding.mode, run.context_overhead)

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
                        partial_history_ref=partial_history_ref,
                        store=store,
                        request_limit=request_limit,
                        drop_ref=drop_ref,
                    )

            _finalize(
                run,
                turn,
                store=store,
                # The completed path measures against the real `start` and carries the
                # verifier's own drop range, where a flush hands over an already-sliced
                # list — hence its own context rather than `_flush_context()`.
                context=PersistContext(
                    conversation_id=conversation_id,
                    start=start,
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
    capabilities: ServiceContainer = _NO_CAPS,
    store: ConversationStore | None = None,
    disabled_tools: frozenset[str] = frozenset(),
) -> Orchestrator:
    """Resume a parked turn with the operator's approve/deny decisions."""

    async def orchestrate(run: Run) -> None:
        results = DeferredToolResults(approvals=decisions)

        # Same reasoning as the chat orchestrator's `_on_timeout`: a resumed turn is
        # bound by fresh wall-clock/inactivity timeouts too (see `RunRegistry.resume`),
        # so it needs the same flush-before-force-cancel hook.
        partial_history_ref: list[Callable[[], list[ModelMessage]]] = []
        # Unlike a chat turn, a resume's destination is already settled — it rode here on
        # the `ParkedTurn` — so the context is constant and only the messages move.
        flush = TurnFlush(
            run,
            messages=lambda: partial_history_ref[0]() if partial_history_ref else [],
            context=lambda: _parked_context(parked),
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
                disabled_tools=disabled_tools,
                # From the parked payload, not a fresh read: the resumed turn must work
                # in the same place the parked one did.
                binding=parked.binding,
                partial_history_ref=partial_history_ref,
                store=store,
                # The ceiling the parked turn was running under — a resume continues
                # under the same one rather than reverting to the config default.
                request_limit=parked.request_limit,
            )
            _finalize(run, turn, store=store, context=_parked_context(parked))
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
