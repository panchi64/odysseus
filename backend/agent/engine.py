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
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from pydantic_ai import (
    Agent,
    DeferredToolRequests,
    DeferredToolResults,
    ModelMessage,
    ModelResponse,
    RunUsage,
    ToolApproved,
    ToolCallPart,
    UsageLimitExceeded,
    UsageLimits,
)
from pydantic_ai.capabilities import ProcessHistory, ReinjectSystemPrompt
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
    ApprovalRequired,
    ConversationTitled,
    LimitNotice,
    Orchestrator,
    Run,
    RunMetrics,
    RunStatus,
)
from services.approval_grants import ApprovalGrantStore, covered_by_grant
from services.conversations import ConversationStore, context_footprint
from services.notifications import NotificationService
from services.uploads import UploadStore
from tools import CompactionContext, InstructionProvider, RunDeps, build_agent_toolsets

from .attachments import resolve_attachments
from .compaction import build_compaction_context, compact_tool_returns
from .meta import Judge, LoopBreaker, LoopDetected, make_utility_judge
from .title import generate_title, last_user_text, title_from_history
from .translate import stream_agent_run

logger = logging.getLogger(__name__)

# A shared empty bag for the no-capabilities default — every capability-backed tool
# degrades uniformly. Never mutated (only construction sites add), so safe to share.
_NO_CAPS = ServiceContainer()

# Persistent stop markers for the cancel/unhandled-error flush paths (mirrors the
# bound-hit details above them — a plain sentence, not internal jargon — stamped via
# `_finalize`'s `blocked_reason` so a reload shows the same explanation the live
# stream did, without touching `run.status`, which the registry itself decides).
_CANCELLED_DETAIL = "cancelled by the operator"
_ERRORED_DETAIL = "an unexpected error stopped this turn"


@dataclass(frozen=True)
class TitleContext:
    """What auto-titling needs, bundled so it can ride a parked turn to its resume.
    The model + its reasoning-off settings come resolved together from the registry
    (titling is a fast, no-reasoning pass). Absent ⇒ titling is off for this run."""

    model: Model
    settings: ModelSettings


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
    # capped attachment content (and stamps the ids) when the resume finally persists it —
    # keeping replayed history capped just like a direct turn.
    attachment_ids: list[str] = field(default_factory=list)
    persisted: list | None = None
    # The turn's resolved compaction context (config + handle map), carried so the resume
    # condenses prior turns the same way — and can still expand a result digested before the park.
    compaction: CompactionContext | None = None


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
        # ReinjectSystemPrompt keeps our system prompt authoritative; ProcessHistory digests
        # oversized prior-turn tool results for the model's view (a no-op unless the turn's
        # RunDeps carries an enabled CompactionContext). Both transform only what the model
        # sees, never what we persist.
        capabilities=[
            ReinjectSystemPrompt(replace_existing=True),
            ProcessHistory(compact_tool_returns),
        ],
    )

    # Feature-contributed dynamic instructions (each manifest's `instructions` export —
    # the document state, the skill catalog): re-resolved fresh each turn, so they're
    # always current and, unlike an appended prompt, never accumulate in history. Each
    # resolves its own capability from the run's bag and no-ops (returns "") when the
    # capability isn't wired, so registration is unconditional.
    for provider in instruction_providers:
        agent.instructions(provider)

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


def _summarize(name: str, args: dict[str, Any]) -> str:
    rendered = ", ".join(f"{k}={v!r}" for k, v in args.items())
    return f"{name}({rendered})"


def _sum_tokens(prior: int | None, delta: int | None) -> int | None:
    """Add two optional token counts, keeping ``None`` only when both are unknown."""
    if prior is None and delta is None:
        return None
    return (prior or 0) + (delta or 0)


def _turn_metrics(
    base: RunMetrics | None, usage: RunUsage, run: Run, messages: list[ModelMessage]
) -> RunMetrics:
    """The run's metrics from the pre-turn ``base`` plus this turn's accumulating ``usage``.

    ``context_used`` is the *footprint* — the last response's prompt+generation, not the run's
    summed tokens — so a multi-step turn doesn't overstate fullness. Built in one place so the
    live per-step frames (the context gauge) and the stashed terminal metrics never diverge."""
    return RunMetrics(
        steps=(base.steps if base else 0) + usage.requests,
        tool_calls=(base.tool_calls if base else 0) + usage.tool_calls,
        input_tokens=_sum_tokens(base.input_tokens if base else None, usage.input_tokens),
        output_tokens=_sum_tokens(base.output_tokens if base else None, usage.output_tokens),
        context_window=run.context_window,
        context_used=context_footprint(messages),
    )


async def _approval_conversation_title(
    store: ConversationStore | None, owner_id: str, conversation_id: str | None
) -> str:
    """A short, human name for the conversation a park's notification names — the
    conversation's own title when one exists (auto-titling may not have run yet on a
    fresh thread), else a plain fallback. Never raises: a lookup failure degrades to
    the fallback rather than losing the notification over a cosmetic detail."""
    if store is not None and conversation_id is not None:
        try:
            summary = await store.get_summary(conversation_id, owner_id)
        except Exception:  # noqa: BLE001 — a title lookup must not block the notify
            summary = None
        if summary is not None and summary.title:
            return summary.title
    return "this conversation"


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
        title = await _approval_conversation_title(store, run.owner_id, conversation_id)
        try:
            await notifications.notify(
                run.owner_id,
                "approval_needed",
                f'"{title}" needs approval for {", ".join(sorted(pending_names))}',
                conversation_id=conversation_id,
                run_id=run.id,
            )
        except Exception:  # noqa: BLE001 — a notify failure must not break the park
            logger.warning(
                "approval_needed notification failed for run %s", run.id, exc_info=True
            )
    run.park(ParkedTurn(agent, messages, requests, announced, pre_approved=pre_approved))


# On-demand inference servers (LM Studio, llama.cpp, …) reject a request for a
# model they couldn't bring up with a terse, mechanical message. The most common
# cause here is a side-by-side compare firing two *unloaded* models at once: the
# server can only cold-load one at a time, so the second aborts.
_MODEL_LOAD_MARKERS = ("failed to load model", "engine protocol startup was aborted")


def _model_load_hint(exc: ModelHTTPError) -> str | None:
    """An operator-actionable message if ``exc`` is an engine model-load failure,
    else ``None`` (leave other HTTP errors with their own detail). The fix is
    engine-side, so the hint points there rather than implying an app bug."""
    if not any(marker in str(exc).lower() for marker in _MODEL_LOAD_MARKERS):
        return None
    model = exc.model_name or "the selected model"
    return (
        f"Couldn't load {model!r} on its inference server. Load it before use — in "
        "LM Studio, pre-load each model you want to compare, or raise “Max loaded "
        "models” / enable JIT so the server can hold more than one at once."
    )


# How the common providers/engines phrase "the prompt is bigger than the context window":
# OpenAI ("maximum context length … context_length_exceeded"), Anthropic ("prompt is too
# long"), and local servers (llama.cpp/LM Studio/vLLM — "exceeds context", "context size",
# "n_ctx"). Matched case-insensitively as substrings of the error text, so each marker must be
# specific enough that an *unrelated* error can't carry it: deliberately omitted are generic
# phrasings ("context window", "too many tokens", "reduce the length") that also appear in
# rate-limit/validation errors — misclassifying those would block the run with a misleading
# context-window stop and swallow the real, actionable error.
_CONTEXT_OVERFLOW_MARKERS = (
    "context length",
    "context_length_exceeded",
    "maximum context",
    "prompt is too long",
    "exceeds context",
    "exceed context",
    "context size",
    "n_ctx",
)


def _is_context_overflow(exc: ModelHTTPError) -> bool:
    """Whether ``exc`` is the model refusing a prompt that overran its context window."""
    return any(marker in str(exc).lower() for marker in _CONTEXT_OVERFLOW_MARKERS)


def _context_limit_message(run: Run) -> str:
    """The operator-facing stop message — names the model's context window (the number the
    operator needs) when known, and what to do next."""
    window = run.context_window
    ceiling = f" of {window:,} tokens" if window else ""
    return (
        f"This conversation reached the model's context window{ceiling} and can't continue. "
        "Start a new chat, or edit/rewind to remove earlier messages, to keep going."
    )


def _usage_limit_kind(exc: UsageLimitExceeded) -> str:
    """Which bound in ``UsageLimits`` tripped — ``UsageLimitExceeded`` carries no
    structured field, only a message, so classify it by the marker each check raises
    (see ``pydantic_ai.usage.UsageLimits``)."""
    message = str(exc)
    if "tool_calls_limit" in message:
        return "tool_calls"
    if "tokens_limit" in message:
        return "tokens"
    return "steps"


def _usage_limit_message(exc: UsageLimitExceeded) -> str:
    """An operator-legible sentence for a usage-limit stop, mirroring the treatment
    ``_timeout_message`` (``runs/registry.py``) gives wall-clock/inactivity bounds:
    this reaches the operator verbatim, as the toast (``LimitNotice.message``), so it
    must read as a plain sentence — never ``str(exc)``'s raw internal phrasing (e.g.
    pydantic_ai's own ``{tool_calls=}`` repr syntax)."""
    kind = _usage_limit_kind(exc)
    if kind == "tool_calls":
        return "this run made too many tool calls and stopped"
    if kind == "tokens":
        return "this run generated too many tokens and stopped"
    return "this run took too many steps and stopped"


def _drop_dangling_tool_calls(messages: list[ModelMessage]) -> list[ModelMessage]:
    """Strip a trailing tool call that never received its result.

    A turn stopped at a bound (usage limit, loop guard, timeout) can leave history ending
    on a ``ModelResponse`` whose ``ToolCallPart`` has no matching ``ToolReturnPart`` — the
    call was requested but the bound tripped before it ran. Persisting that and replaying it
    on the next turn is a provider error (an assistant tool call with no following tool
    result → HTTP 400), which would break every later turn in the thread. Since this is the
    final message, any tool call in it is necessarily unanswered: drop those parts, and the
    whole message if nothing else remains."""
    if not messages or not isinstance(messages[-1], ModelResponse):
        return messages
    last = messages[-1]
    kept = [p for p in last.parts if not isinstance(p, ToolCallPart)]
    if len(kept) == len(last.parts):
        return messages
    if kept:
        return [*messages[:-1], replace(last, parts=kept)]
    return messages[:-1]


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
    compaction: CompactionContext | None = None,
    partial_history_ref: list[Callable[[], list[ModelMessage]]] | None = None,
    store: ConversationStore | None = None,
) -> _TurnResult:
    settings = get_settings()
    limits = UsageLimits(
        request_limit=settings.agent_request_limit,
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
        # The turn's resolved compaction context (config + persistence boundary + handle map),
        # built once by the orchestrator and shared across the turn's segments (the grant-resume
        # continuations reuse this `deps`), so `expand_tool_result` can recover any digested prior
        # result. None ⇒ compaction is off for this turn.
        compaction=compaction,
    )
    # A turn may run as several segments: the initial model pass, then a continuation
    # for each batch of deferred calls a conversation grant auto-approves. They share
    # ONE usage budget, ONE no-progress guard, and ONE usage accumulator, so the *whole*
    # turn is bounded — a granted tool the model keeps re-calling can't reset the guards
    # (or grow the call stack) by deferring on each hop; it trips the loop/usage stop.
    loop_breaker = LoopBreaker(repeat_threshold=settings.loop_repeat_threshold)
    usage = RunUsage()
    # Metrics from any earlier segment of this run (a verifier correction, an approval
    # resume); captured once so the per-hop accumulation below never double-counts.
    base = run.metrics

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
        run.emit(_turn_metrics(base, usage, run, history))

    # Rebound each loop iteration by `agent.iter()`'s `as agent_run`; stays None only
    # if a bound trips before the context manager assigns it (its `__aenter__` does
    # no request, so this hasn't been observed, but the except blocks below guard
    # it anyway rather than risk an unbound-variable crash on a stop path).
    agent_run: Any = None

    def _partial_history() -> list[ModelMessage]:
        return list(agent_run.ctx.state.message_history) if agent_run is not None else []

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
                )
                result = agent_run.result
        except UsageLimitExceeded as exc:
            # Hit a usage bound — stop and report state, don't error.
            run.emit(LimitNotice(limit=_usage_limit_kind(exc), message=_usage_limit_message(exc)))
            detail = "usage limit reached"
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
            if _is_context_overflow(exc):
                run.emit(LimitNotice(limit="context", message=_context_limit_message(run)))
                detail = "context window exceeded"
                run.block(detail)
                return _TurnResult(
                    answer=None,
                    messages=_partial_history(),
                    blocked_reason=detail,
                )
            # Rewrite a model-couldn't-load error into something the operator can act
            # on; let every other HTTP error propagate with its own detail.
            hint = _model_load_hint(exc)
            if hint is None:
                raise
            raise ModelLoadError(hint) from exc

        output = result.output
        messages = result.all_messages()
        # ``usage`` accumulates across hops, so add it onto the pre-turn ``base`` once —
        # ``base`` already holds earlier segments' totals.
        run.set_metrics(_turn_metrics(base, usage, run, messages))
        if not (isinstance(output, DeferredToolRequests) and output.approvals):
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
    compaction: CompactionContext | None = None,
    partial_history_ref: list[Callable[[], list[ModelMessage]]] | None = None,
    store: ConversationStore | None = None,
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
        compaction=compaction,
        partial_history_ref=partial_history_ref,
        store=store,
    )
    if run.status is RunStatus.awaiting_input:
        # The correction needs approval: carry the drop range on the parked turn
        # so the resume's persist drops the rejected answer + nudge as well.
        if isinstance(run.parked_payload, ParkedTurn):
            run.parked_payload.clean_drop = clean_drop
        return corrected
    if corrected.answer is None:
        return corrected  # hit a bound — caller finalizes it
    return _TurnResult(answer=corrected.answer, messages=corrected.messages, clean_drop=clean_drop)


def _finalize(
    run: Run,
    turn: _TurnResult,
    *,
    store: ConversationStore | None,
    conversation_id: str | None,
    start: int,
    clean_drop: tuple[int, int] | None = None,
    attachment_ids: list[str] | None = None,
    persisted: list | None = None,
    compaction: CompactionContext | None = None,
) -> None:
    """Close out a turn: persist it, or wire resume context if it parked.

    Shared by the chat and resume orchestrators so the park/answer-None guards
    are applied *after* the verifier too (a corrective re-attempt can itself park
    or hit a bound). ``clean_drop`` is a verifier correction's message range to
    drop from the persisted history. ``attachment_ids``/``persisted`` carry a turn's
    attached files: the ids are stamped on the persisted request (chip rendering),
    and ``persisted`` is the capped content that replaces the live payload in history."""
    if run.status is RunStatus.awaiting_input:
        # Parked: hand the resume the context to persist the parked turn too.
        if conversation_id is not None and isinstance(run.parked_payload, ParkedTurn):
            run.parked_payload.conversation_id = conversation_id
            run.parked_payload.persist_from = start
            if clean_drop is not None:  # re-park: carry the drop range forward
                run.parked_payload.clean_drop = clean_drop
            run.parked_payload.attachment_ids = attachment_ids or []
            run.parked_payload.persisted = persisted
            run.parked_payload.compaction = compaction
        return
    if turn.answer is None and not turn.blocked_reason:
        return  # hit a bound with nothing captured, or a cancel — nothing to persist
    if store is not None and conversation_id is not None:
        messages = turn.messages
        if clean_drop is not None:
            reject_idx, nudge_idx = clean_drop
            messages = messages[:reject_idx] + messages[nudge_idx + 1 :]
        # The store installs the capped `persisted` content and stamps `attachment_ids`
        # on the turn's user request as it serializes — keeping replayed history capped is
        # the store's concern (what the durable blob contains), not the engine's.
        # `blocked_reason` stamps the turn's branch node so a reload shows the same
        # persistent stop marker the live stream rendered (`record` is a no-op for an
        # empty slice, e.g. a bound hit before any new message accumulated).
        store.record(
            conversation_id,
            messages[start:],
            attachment_ids=attachment_ids or [],
            persisted=persisted,
            blocked_reason=turn.blocked_reason,
        )


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
    _finalize(
        run,
        _TurnResult(
            answer=None,
            messages=parked.message_history,
            blocked_reason=_CANCELLED_DETAIL,
        ),
        store=store,
        conversation_id=parked.conversation_id,
        start=parked.persist_from,
        clean_drop=parked.clean_drop,
        attachment_ids=parked.attachment_ids,
        persisted=parked.persisted,
        compaction=parked.compaction,
    )


async def _maybe_title(
    run: Run,
    *,
    title: TitleContext | None,
    store: ConversationStore | None,
    conversation_id: str | None,
    is_first_turn: bool,
) -> None:
    """Auto-name a fresh conversation from the operator's opening message.

    The resume path's namer: a first turn that parked for approval is named once it
    resumes to completion. The user's first message is read from the just-persisted
    history rather than threaded in (the resume has no ``prompt`` in hand). The
    initial chat orchestrator instead titles concurrently via :func:`_start_title` /
    :func:`_emit_title` so it adds no post-answer delay. The title reflects what the operator
    asked — the assistant's reply is deliberately not fed to the namer. Guards:

    - ``is_first_turn`` (no prior messages) is the cheap pre-filter that skips the
      model call on continuation turns;
    - :meth:`ConversationStore.set_title_if_absent` is the authoritative guard —
      it fills only a blank title, so an operator-named thread is never clobbered,
      and we announce ``conversation.titled`` only when it actually set the name.

    Emitted before the orchestrator returns (before ``run.ended``) so the open
    stream carries it. Best-effort throughout: any failure leaves the thread
    untitled without disturbing the finished turn."""
    if not is_first_turn or title is None or store is None or conversation_id is None:
        return
    try:
        name = await title_from_history(
            title.model,
            await store.history(conversation_id),
            reasoning_off=title.settings,
            timeout_s=get_settings().title_timeout_s,
            max_tokens=get_settings().title_max_tokens,
        )
        await _announce_title(run, name, store=store, conversation_id=conversation_id)
    except Exception:  # noqa: BLE001 — titling is best-effort, not turn-critical
        logger.warning("auto-titling failed for %s", conversation_id, exc_info=True)


async def _announce_title(
    run: Run,
    name: str | None,
    *,
    store: ConversationStore | None,
    conversation_id: str | None,
) -> None:
    """Persist a generated title (fill-only-if-blank) and announce it on success.

    :meth:`ConversationStore.set_title_if_absent` is the authoritative guard — it
    fills only a blank title, so an operator-named thread is never clobbered, and
    ``conversation.titled`` is announced only when it actually set the name. Shared
    by both the concurrent (:func:`_emit_title`) and resume (:func:`_maybe_title`)
    paths."""
    if not name or store is None or conversation_id is None:
        return
    if await store.set_title_if_absent(conversation_id, name):
        run.emit(ConversationTitled(conversation_id=conversation_id, title=name))


def _start_title(
    title: TitleContext | None, prompt: str | None
) -> asyncio.Task[str | None] | None:
    """Begin generating a thread title concurrently with the turn's answer.

    Titling needs only the operator's opening message, which a first turn already
    has in ``prompt`` — so there's no need to wait for the answer (or persistence)
    first. Overlapping it with the (longer) answer means it adds no post-answer
    latency, while the result is still emitted before ``run.ended``. Returns ``None``
    when titling is off or there is nothing to name from. The call stays bounded by
    ``title_timeout_s``."""
    if title is None or not prompt:
        return None
    return asyncio.create_task(
        generate_title(
            title.model,
            prompt,
            reasoning_off=title.settings,
            timeout_s=get_settings().title_timeout_s,
            max_tokens=get_settings().title_max_tokens,
        )
    )


async def _emit_title(
    run: Run,
    task: asyncio.Task[str | None] | None,
    *,
    store: ConversationStore | None,
    conversation_id: str | None,
) -> None:
    """Await the concurrently-started title and announce it. Emitted before the
    orchestrator returns (``run.ended``) so the open stream carries it. Best-effort:
    any failure leaves the thread untitled without disturbing the turn."""
    if task is None:
        return
    try:
        await _announce_title(
            run, await task, store=store, conversation_id=conversation_id
        )
    except Exception:  # noqa: BLE001 — titling is best-effort, not turn-critical
        logger.warning("auto-titling failed for %s", conversation_id, exc_info=True)


async def _discard_title(task: asyncio.Task[str | None] | None) -> None:
    """Abandon a concurrently-started title (the turn parked, raised, or was
    cancelled): cancel it and drain the cancellation so the title-model call does
    not outlive the run."""
    if task is None or task.done():
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


def build_chat_orchestrator(
    prompt: str | None,
    *,
    model: Model,
    categories: Any = None,
    instruction_providers: Sequence[InstructionProvider] = (),
    judge: Judge | None = None,
    utility_model: Model | None = None,
    utility_settings: ModelSettings | None = None,
    title_model: Model | None = None,
    title_settings: ModelSettings | None = None,
    capabilities: ServiceContainer = _NO_CAPS,
    store: ConversationStore | None = None,
    conversation_id: str | None = None,
    context_window: int | None = None,
    uploads: UploadStore | None = None,
    attachment_ids: list[str] | None = None,
    vision: bool = False,
    inline_max_tokens: int | None = None,
    compaction: CompactionContext | None = None,
    disabled_tools: frozenset[str] = frozenset(),
) -> Orchestrator:
    """Build the orchestrator for one chat turn (one always-agent path).

    ``prompt`` is the operator's message, or ``None`` to **regenerate**: re-run
    from a history that already ends in the user request (the caller moved the
    active leaf there), producing a fresh answer as a sibling of the previous one.

    ``attachment_ids`` are files the operator attached to *this* message (resolved
    via ``uploads``; ``vision`` selects image-as-pixels vs extracted text). They're
    handed to the model in full for this turn, then retained inline on persist up to
    ``inline_max_tokens`` (the operator's cap; absent ⇒ the config default) — images
    always, a document's text until it exceeds the cap, past which it's cut off with a
    pointer to the attachments/corpus tools. Attachments are injected only on a fresh
    turn; a regenerate (``prompt is None``) re-runs prior history, which already carries
    the capped content.

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
    """
    async def orchestrate(run: Run) -> None:
        settings = get_settings()
        run.context_window = context_window
        agent = _build_agent(
            model, categories=categories, instruction_providers=instruction_providers
        )
        announced: set[str] = set()
        history = (
            await store.history(conversation_id)
            if store is not None and conversation_id is not None
            else None
        )
        # A prior turn stopped at a bound persists its transcript verbatim — which can end on
        # an assistant tool call that never got its result. That full record is right for the
        # operator's view, but replaying a dangling tool call to the model is a provider error
        # (an assistant tool_call with no following tool result → HTTP 400), so strip it from
        # the *model's* input here. The persisted transcript is untouched; only this turn's
        # model history is sanitized, and `start` tracks the trimmed length.
        if history:
            history = _drop_dangling_tool_calls(history)
        start = len(history) if history else 0
        is_first_turn = start == 0

        # Resolve the turn's compaction context once and anchor its boundary to the persistence
        # index: everything from `start` on is this (to-be-persisted) turn and stays full, so a
        # verifier re-attempt's injected nudge can't push the original tool returns onto the
        # "prior" side. The same object rides every segment (drive → verify → finalize → resume),
        # keeping one handle map so a result digested before an approval park can still be expanded.
        active_compaction = (
            compaction if compaction is not None else build_compaction_context(settings)
        )
        active_compaction.protect_from = start

        # Auto-title context for this run — None disables it (feature off, or no
        # utility model). Built up-front so the title can be generated *concurrently*
        # with the answer (it needs only the operator's opening message), leaving no
        # post-answer "writing" tail. Only a fresh thread's first turn is named.
        title_ctx = (
            TitleContext(title_model, title_settings or {})
            if title_model is not None and settings.title_enabled
            else None
        )
        title_task = _start_title(title_ctx if is_first_turn else None, prompt)

        # Hand any attached files to the model in full for *this* turn — pixels for a
        # vision model, extracted text otherwise — appended after the operator's prompt.
        # On persist they're replaced by the capped `persisted` set (images + under-cap
        # text inline, larger text cut to a tool pointer), so replayed history stays
        # bounded. Only on a fresh turn: a regenerate (prompt is None) re-runs history,
        # which already carries the capped content. The cap is the operator's setting,
        # passed in; absent ⇒ the config default.
        cap = (
            inline_max_tokens
            if inline_max_tokens is not None
            else settings.attachment_inline_max_tokens
        )
        persisted: list | None = None
        stamp_ids: list[str] = []
        user_prompt: str | list[Any] | None = prompt
        if attachment_ids and prompt is not None and uploads is not None:
            resolved = await resolve_attachments(
                uploads, run.owner_id, attachment_ids, vision=vision, inline_max_tokens=cap
            )
            # Only build a multimodal prompt when something actually resolved — else leave
            # the plain string, so an all-deleted-ids turn doesn't persist as a bare list
            # (which the projection would read as empty text). Stamp only resolved ids as
            # chips; foreign/deleted ids are dropped.
            if resolved.content:
                user_prompt = [prompt, *resolved.content]
            persisted = resolved.persisted or None
            stamp_ids = resolved.ids

        # Reachable mid-turn so a wall-clock/inactivity bound can flush whatever the
        # turn has produced before the registry force-cancels this task (which would
        # otherwise interrupt us before we reach `_finalize` below and silently drop
        # the turn on the next reload — see `RunRegistry._flush_timeout`).
        partial_history_ref: list[Callable[[], list[ModelMessage]]] = []

        def _on_timeout(detail: str) -> None:
            # `detail` is already the operator-legible message the registry built
            # (`RunTimeout.__str__`, from the bound's configured duration) — reused
            # verbatim so the persisted marker matches the toast the live stream showed.
            if not partial_history_ref:
                return
            run.block(detail)
            _finalize(
                run,
                _TurnResult(answer=None, messages=partial_history_ref[0](), blocked_reason=detail),
                store=store,
                conversation_id=conversation_id,
                start=start,
                attachment_ids=stamp_ids,
                persisted=persisted,
                compaction=active_compaction,
            )

        def _on_cancel() -> None:
            # The cancel counterpart of `_on_timeout` above: same pre-cancel flush,
            # but must not call `run.block(...)` — the registry's own
            # `except asyncio.CancelledError` handler sets the terminal `cancelled`
            # status once the cancellation lands, and that must not be clobbered.
            if not partial_history_ref:
                return
            _finalize(
                run,
                _TurnResult(
                    answer=None,
                    messages=partial_history_ref[0](),
                    blocked_reason=_CANCELLED_DETAIL,
                ),
                store=store,
                conversation_id=conversation_id,
                start=start,
                attachment_ids=stamp_ids,
                persisted=persisted,
                compaction=active_compaction,
            )

        run.on_timeout = _on_timeout
        run.on_cancel = _on_cancel
        # Guards the `except Exception` flush below from double-persisting: once the
        # normal `_finalize` call has run, the only remaining calls are the best-effort
        # titling helpers, which already swallow their own exceptions internally — but
        # this stays the authoritative check rather than relying on that.
        finalized = False
        try:
            turn = await _drive_turn(
                run,
                agent,
                prompt=user_prompt,
                message_history=history,
                announced=announced,
                caps=capabilities,
                conversation_id=conversation_id,
                disabled_tools=disabled_tools,
                compaction=active_compaction,
                partial_history_ref=partial_history_ref,
                store=store,
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
                        compaction=active_compaction,
                        partial_history_ref=partial_history_ref,
                        store=store,
                    )

            _finalize(
                run,
                turn,
                store=store,
                conversation_id=conversation_id,
                start=start,
                clean_drop=turn.clean_drop,
                attachment_ids=stamp_ids,
                persisted=persisted,
                compaction=active_compaction,
            )
            # Disarm the flush hooks now the turn is recorded: a wall-clock/inactivity bound
            # or a cancel landing during the post-answer title window (below) must not
            # re-run `_finalize` and double-record the turn (or stamp a spurious stop on a
            # completed answer).
            run.on_timeout = None
            run.on_cancel = None
            finalized = True

            if run.status is RunStatus.awaiting_input:
                # Arm the park-cancel flush now, before any further `await` — a
                # concurrent cancel of this now-externally-visible parked run must
                # find `ParkedTurn`'s persistence context already wired (see
                # `_persist_parked_cancel`'s docstring for why this can't wait until
                # after `_discard_title`'s own await below).
                run.on_park_cancel = lambda: _persist_parked_cancel(run, store=store)
                # Parked for approval before producing an answer: abandon the
                # concurrent title and carry the context forward so the resume names
                # the thread once it completes (the resume titles from history).
                await _discard_title(title_task)
                if isinstance(run.parked_payload, ParkedTurn):
                    run.parked_payload.title = title_ctx
            else:
                # Announce the title started up-front — a cosmetic follow-on that, run
                # concurrently with the answer, doesn't gate it. Emitted before the
                # orchestrator returns (run.ended), so the open stream carries it.
                await _emit_title(
                    run, title_task, store=store, conversation_id=conversation_id
                )
        except Exception:
            # Anything else that escapes `_drive_turn` (a provider error its specific
            # catches don't cover, a tool/dependency raising, …) must still not silently
            # drop the operator's own prompt: persist whatever the turn had produced,
            # carrying a legible marker, before this propagates to the registry's own
            # generic handler, which records the run as `error`. Mirrors the
            # timeout/cancel flush above but never touches `run.status` — the registry
            # is the one that decides the terminal outcome for an unhandled exception.
            if not finalized and partial_history_ref:
                _finalize(
                    run,
                    _TurnResult(
                        answer=None,
                        messages=partial_history_ref[0](),
                        blocked_reason=_ERRORED_DETAIL,
                    ),
                    store=store,
                    conversation_id=conversation_id,
                    start=start,
                    attachment_ids=stamp_ids,
                    persisted=persisted,
                    compaction=active_compaction,
                )
                finalized = True
            # Disarm now that this path has (or the normal path already did) recorded
            # the turn — the task is unwinding, so no further hook call is legitimate.
            run.on_timeout = None
            run.on_cancel = None
            raise
        finally:
            # Safety net: if the turn raised or was cancelled before the title was
            # consumed above, don't let the detached title-model call outlive the run.
            if title_task is not None and not title_task.done():
                title_task.cancel()

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

        def _on_timeout(detail: str) -> None:
            # `detail` is already the operator-legible message the registry built
            # (`RunTimeout.__str__`, from the bound's configured duration) — reused
            # verbatim so the persisted marker matches the toast the live stream showed.
            if not partial_history_ref:
                return
            run.block(detail)
            _finalize(
                run,
                _TurnResult(answer=None, messages=partial_history_ref[0](), blocked_reason=detail),
                store=store,
                conversation_id=parked.conversation_id,
                start=parked.persist_from,
                clean_drop=parked.clean_drop,
                attachment_ids=parked.attachment_ids,
                persisted=parked.persisted,
                compaction=parked.compaction,
            )

        def _on_cancel() -> None:
            # The cancel counterpart of `_on_timeout` above — see the chat
            # orchestrator's `_on_cancel` for why this must not call `run.block(...)`.
            if not partial_history_ref:
                return
            _finalize(
                run,
                _TurnResult(
                    answer=None,
                    messages=partial_history_ref[0](),
                    blocked_reason=_CANCELLED_DETAIL,
                ),
                store=store,
                conversation_id=parked.conversation_id,
                start=parked.persist_from,
                clean_drop=parked.clean_drop,
                attachment_ids=parked.attachment_ids,
                persisted=parked.persisted,
                compaction=parked.compaction,
            )

        run.on_timeout = _on_timeout
        run.on_cancel = _on_cancel
        # See the chat orchestrator's identical guard: makes the `except Exception`
        # flush below a no-op once the normal `_finalize` call has already run.
        finalized = False
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
                compaction=parked.compaction,
                partial_history_ref=partial_history_ref,
                store=store,
            )
            _finalize(
                run,
                turn,
                store=store,
                conversation_id=parked.conversation_id,
                start=parked.persist_from,
                clean_drop=parked.clean_drop,
                attachment_ids=parked.attachment_ids,
                persisted=parked.persisted,
                compaction=parked.compaction,
            )
            # Disarm the flush hooks now the turn is recorded — a bound or cancel
            # landing during the title window below must not re-finalize (see the
            # chat orchestrator).
            run.on_timeout = None
            run.on_cancel = None
            finalized = True

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
                await _maybe_title(
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
            if not finalized and partial_history_ref:
                _finalize(
                    run,
                    _TurnResult(
                        answer=None,
                        messages=partial_history_ref[0](),
                        blocked_reason=_ERRORED_DETAIL,
                    ),
                    store=store,
                    conversation_id=parked.conversation_id,
                    start=parked.persist_from,
                    clean_drop=parked.clean_drop,
                    attachment_ids=parked.attachment_ids,
                    persisted=parked.persisted,
                    compaction=parked.compaction,
                )
                finalized = True
            # Disarm now that this path has (or the normal path already did) recorded
            # the turn — the task is unwinding, so no further hook call is legitimate.
            run.on_timeout = None
            run.on_cancel = None
            raise

    return orchestrate
