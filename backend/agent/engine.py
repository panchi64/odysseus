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

import logging
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai import (
    Agent,
    DeferredToolRequests,
    DeferredToolResults,
    ModelMessage,
    UsageLimitExceeded,
    UsageLimits,
)
from pydantic_ai.capabilities import ReinjectSystemPrompt
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings

from core.config import get_settings
from prompts.agent import INSTRUCTIONS, SYSTEM_PROMPT, VERIFIER_NUDGE
from runs import (
    ApprovalRequired,
    ConversationTitled,
    LimitNotice,
    Orchestrator,
    Run,
    RunMetrics,
    RunStatus,
)
from services.conversations import ConversationStore
from tools import Capabilities, RunDeps, build_agent_toolsets

from .meta import Judge, LoopBreaker, LoopDetected, make_utility_judge
from .title import first_user_text, generate_title, last_user_text
from .translate import stream_agent_run

logger = logging.getLogger(__name__)

# A shared empty bundle for the no-capabilities default (frozen ⇒ safe to share).
_NO_CAPS = Capabilities()


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


@dataclass
class _TurnResult:
    """What one turn produced: a final answer (or None if it parked/blocked/hit
    a bound) and the message history needed to continue the conversation."""

    answer: str | None
    messages: list[ModelMessage] = field(default_factory=list)
    # A verifier correction's [reject_idx, nudge_idx] range to drop on persist.
    clean_drop: tuple[int, int] | None = None


def _build_agent(model: Model, *, categories: Any = None) -> Agent:
    # Two prompt seams by durability: SYSTEM_PROMPT (identity/voice) is anchored in
    # history; INSTRUCTIONS (autonomy, tool posture, the treat-external-content-as-
    # data guardrail) are rebuilt fresh from the agent every turn, so a poisoned or
    # reconstructed history can never displace them. ReinjectSystemPrompt keeps the
    # system prompt — the half that *does* live in history — authoritative too,
    # stripping any spoofed system part and reasserting ours on every request.
    # output_type accepts DeferredToolRequests so approval-required tools can defer
    # instead of executing; normal turns still return text.
    return Agent(
        model,
        deps_type=RunDeps,
        system_prompt=SYSTEM_PROMPT,
        instructions=INSTRUCTIONS,
        toolsets=build_agent_toolsets(categories),
        output_type=[str, DeferredToolRequests],
        capabilities=[ReinjectSystemPrompt(replace_existing=True)],
    )


def _summarize(name: str, args: dict[str, Any]) -> str:
    rendered = ", ".join(f"{k}={v!r}" for k, v in args.items())
    return f"{name}({rendered})"


def _sum_tokens(prior: int | None, delta: int | None) -> int | None:
    """Add two optional token counts, keeping ``None`` only when both are unknown."""
    if prior is None and delta is None:
        return None
    return (prior or 0) + (delta or 0)


def _park_for_approval(
    run: Run,
    agent: Agent,
    messages: list[ModelMessage],
    requests: DeferredToolRequests,
    announced: set[str],
) -> None:
    for call in requests.approvals:
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
    run.park(ParkedTurn(agent, messages, requests, announced))


async def _drive_turn(
    run: Run,
    agent: Agent,
    *,
    prompt: str | None = None,
    message_history: list[ModelMessage] | None = None,
    deferred_results: DeferredToolResults | None = None,
    announced: set[str],
    caps: Capabilities = _NO_CAPS,
    conversation_id: str | None = None,
) -> _TurnResult:
    settings = get_settings()
    limits = UsageLimits(
        request_limit=settings.agent_request_limit,
        tool_calls_limit=settings.agent_tool_calls_limit,
    )
    deps = RunDeps(
        run=run,
        owner_id=run.owner_id,
        memory=caps.memory,
        sandbox_sessions=caps.sandbox_sessions,
        conversation_id=conversation_id,
        artifacts=caps.artifacts,
        search=caps.search,
    )
    loop_breaker = LoopBreaker(repeat_threshold=settings.loop_repeat_threshold)
    try:
        async with agent.iter(
            prompt,
            deps=deps,
            message_history=message_history,
            deferred_tool_results=deferred_results,
            usage_limits=limits,
        ) as agent_run:
            await stream_agent_run(agent_run, run, announced=announced, loop_breaker=loop_breaker)
            result = agent_run.result
    except UsageLimitExceeded as exc:
        # Hit a usage bound — stop and report state, don't error.
        run.emit(LimitNotice(limit="steps", message=str(exc)))
        run.block("usage limit reached")
        return _TurnResult(answer=None)
    except LoopDetected as exc:
        # No-progress guard tripped — stop and report state, don't error.
        run.emit(LimitNotice(limit="loop", message=str(exc)))
        run.block("stopped: repeated an action without making progress")
        return _TurnResult(answer=None)

    # Accumulate onto any prior metrics so a multi-turn run (a verifier
    # correction, or an approval resume) reports the whole run, not just the
    # last turn.
    usage = result.usage
    prior = run.metrics
    run.set_metrics(
        RunMetrics(
            steps=(prior.steps if prior else 0) + usage.requests,
            tool_calls=(prior.tool_calls if prior else 0) + usage.tool_calls,
            input_tokens=_sum_tokens(prior.input_tokens if prior else None, usage.input_tokens),
            output_tokens=_sum_tokens(prior.output_tokens if prior else None, usage.output_tokens),
        )
    )
    output = result.output
    messages = result.all_messages()
    if isinstance(output, DeferredToolRequests) and output.approvals:
        _park_for_approval(run, agent, messages, output, announced)
        return _TurnResult(answer=None, messages=messages)
    answer = output if isinstance(output, str) else None
    return _TurnResult(answer=answer, messages=messages)


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
    caps: Capabilities = _NO_CAPS,
    conversation_id: str | None = None,
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
) -> None:
    """Close out a turn: persist it, or wire resume context if it parked.

    Shared by the chat and resume orchestrators so the park/answer-None guards
    are applied *after* the verifier too (a corrective re-attempt can itself park
    or hit a bound). ``clean_drop`` is a verifier correction's message range to
    drop from the persisted history."""
    if run.status is RunStatus.awaiting_input:
        # Parked: hand the resume the context to persist the parked turn too.
        if conversation_id is not None and isinstance(run.parked_payload, ParkedTurn):
            run.parked_payload.conversation_id = conversation_id
            run.parked_payload.persist_from = start
            if clean_drop is not None:  # re-park: carry the drop range forward
                run.parked_payload.clean_drop = clean_drop
        return
    if turn.answer is None:
        return  # blocked or hit a bound — nothing to persist
    if store is not None and conversation_id is not None:
        messages = turn.messages
        if clean_drop is not None:
            reject_idx, nudge_idx = clean_drop
            messages = messages[:reject_idx] + messages[nudge_idx + 1 :]
        store.record(conversation_id, messages[start:])


async def _maybe_title(
    run: Run,
    *,
    title: TitleContext | None,
    store: ConversationStore | None,
    conversation_id: str | None,
    is_first_turn: bool,
) -> None:
    """Auto-name a fresh conversation from the operator's opening message.

    Shared by the chat and resume orchestrators (called from both after persist),
    so a first turn that parked for approval is still named once it resumes. The
    user's first message is read from the just-persisted history rather than threaded
    in, so one code path serves both callers. The title reflects what the operator
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
        history = await store.history(conversation_id)
        prompt = first_user_text(history)
        if not prompt:
            return  # nothing to name from (e.g. a non-text opening prompt)
        name = await generate_title(
            title.model,
            prompt,
            reasoning_off=title.settings,
            timeout_s=get_settings().title_timeout_s,
        )
        if not name:
            return
        if await store.set_title_if_absent(conversation_id, name):
            run.emit(ConversationTitled(conversation_id=conversation_id, title=name))
    except Exception:  # noqa: BLE001 — titling is best-effort, not turn-critical
        logger.warning("auto-titling failed for %s", conversation_id, exc_info=True)


def build_chat_orchestrator(
    prompt: str | None,
    *,
    model: Model,
    categories: Any = None,
    judge: Judge | None = None,
    utility_model: Model | None = None,
    title_model: Model | None = None,
    title_settings: ModelSettings | None = None,
    capabilities: Capabilities = _NO_CAPS,
    store: ConversationStore | None = None,
    conversation_id: str | None = None,
) -> Orchestrator:
    """Build the orchestrator for one chat turn (one always-agent path).

    ``prompt`` is the operator's message, or ``None`` to **regenerate**: re-run
    from a history that already ends in the user request (the caller moved the
    active leaf there), producing a fresh answer as a sibling of the previous one.

    ``model`` is the resolved ``main`` model (the route resolves it from the
    registry, with any per-conversation override). ``categories`` overrides the
    tool catalog. The verifier's judge is ``judge`` if injected, else one built
    from ``utility_model`` when given; with neither, verification is skipped (a
    graceful degradation when no utility model is configured). With ``store`` +
    ``conversation_id`` the turn continues prior history and persists its new
    messages; without them it runs stateless. The verifier only runs when enabled
    in settings (and, by default, only on tool-producing turns). With
    ``title_model`` (and ``title_enabled`` in settings) the *first* completed turn
    of a fresh thread is auto-named; ``title_settings`` carries the model's
    reasoning-off settings so the namer runs fast.
    """
    async def orchestrate(run: Run) -> None:
        settings = get_settings()
        agent = _build_agent(model, categories=categories)
        announced: set[str] = set()
        history = (
            await store.history(conversation_id)
            if store is not None and conversation_id is not None
            else None
        )
        start = len(history) if history else 0
        is_first_turn = start == 0

        turn = await _drive_turn(
            run,
            agent,
            prompt=prompt,
            message_history=history,
            announced=announced,
            caps=capabilities,
            conversation_id=conversation_id,
        )

        # Verify only a completed turn (not one parked for approval or stopped at
        # a bound), and only when the heuristic says it is worth judging.
        if (
            run.status is not RunStatus.awaiting_input
            and turn.answer is not None
            and settings.verify_enabled
            and _should_verify(settings, run)
        ):
            judging = judge or (make_utility_judge(utility_model) if utility_model else None)
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
                )

        _finalize(
            run,
            turn,
            store=store,
            conversation_id=conversation_id,
            start=start,
            clean_drop=turn.clean_drop,
        )

        # Auto-title context for this run — None disables it (feature off, or no
        # utility model). Built here so it can ride a parked turn to its resume.
        title_ctx = (
            TitleContext(title_model, title_settings or {})
            if title_model is not None and settings.title_enabled
            else None
        )
        if run.status is RunStatus.awaiting_input:
            # Parked for approval before producing an answer: carry the title
            # context so the resume names the thread once it completes.
            if isinstance(run.parked_payload, ParkedTurn):
                run.parked_payload.title = title_ctx
        else:
            # Name the thread after persisting it — a cosmetic follow-on that must
            # not gate the answer. Emitted before the orchestrator returns
            # (run.ended), so the open stream carries it.
            await _maybe_title(
                run,
                title=title_ctx,
                store=store,
                conversation_id=conversation_id,
                is_first_turn=is_first_turn,
            )

    return orchestrate


def build_resume_orchestrator(
    parked: ParkedTurn,
    decisions: dict[str, Any],
    *,
    capabilities: Capabilities = _NO_CAPS,
    store: ConversationStore | None = None,
) -> Orchestrator:
    """Resume a parked turn with the operator's approve/deny decisions."""

    async def orchestrate(run: Run) -> None:
        results = DeferredToolResults(approvals=decisions)
        turn = await _drive_turn(
            run,
            parked.agent,
            message_history=parked.message_history,
            deferred_results=results,
            announced=parked.announced,
            caps=capabilities,
            conversation_id=parked.conversation_id,
        )
        _finalize(
            run,
            turn,
            store=store,
            conversation_id=parked.conversation_id,
            start=parked.persist_from,
            clean_drop=parked.clean_drop,
        )

        if run.status is RunStatus.awaiting_input:
            # Re-parked on a further approval: carry the title context forward to
            # the new parked payload so the eventual completion still names it.
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

    return orchestrate
