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
from pydantic_ai.models import Model

from core.config import get_settings
from runs import ApprovalRequired, LimitNotice, Orchestrator, Run, RunMetrics, RunStatus
from services import llm
from services.conversations import ConversationStore
from tools import RunDeps, build_agent_toolsets

from .meta import Judge, LoopBreaker, LoopDetected, utility_judge
from .translate import stream_agent_run


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


@dataclass
class _TurnResult:
    """What one turn produced: a final answer (or None if it parked/blocked/hit
    a bound) and the message history needed to continue the conversation."""

    answer: str | None
    messages: list[ModelMessage] = field(default_factory=list)
    # A verifier correction's [reject_idx, nudge_idx] range to drop on persist.
    clean_drop: tuple[int, int] | None = None


def _build_agent(model: Model, *, categories: Any = None) -> Agent:
    # output_type accepts DeferredToolRequests so approval-required tools can
    # defer instead of executing; normal turns still return text.
    return Agent(
        model,
        deps_type=RunDeps,
        toolsets=build_agent_toolsets(categories),
        output_type=[str, DeferredToolRequests],
    )


def _summarize(name: str, args: dict[str, Any]) -> str:
    rendered = ", ".join(f"{k}={v!r}" for k, v in args.items())
    return f"{name}({rendered})"


def _park_for_approval(
    run: Run, agent: Agent, result: Any, requests: DeferredToolRequests, announced: set[str]
) -> None:
    for call in requests.approvals:
        args = call.args_as_dict()
        run.emit(
            ApprovalRequired(
                tool_call_id=call.tool_call_id,
                name=call.tool_name,
                args=args,
                summary=_summarize(call.tool_name, args),
            )
        )
    run.park(ParkedTurn(agent, result.all_messages(), requests, announced))


async def _drive_turn(
    run: Run,
    agent: Agent,
    *,
    prompt: str | None = None,
    message_history: list[ModelMessage] | None = None,
    deferred_results: DeferredToolResults | None = None,
    announced: set[str],
) -> _TurnResult:
    settings = get_settings()
    limits = UsageLimits(
        request_limit=settings.agent_request_limit,
        tool_calls_limit=settings.agent_tool_calls_limit,
    )
    deps = RunDeps(run=run, owner_id=run.owner_id)
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

    usage = result.usage
    run.set_metrics(
        RunMetrics(
            steps=usage.requests,
            tool_calls=usage.tool_calls,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )
    )
    output = result.output
    if isinstance(output, DeferredToolRequests) and output.approvals:
        _park_for_approval(run, agent, result, output, announced)
        return _TurnResult(answer=None, messages=result.all_messages())
    answer = output if isinstance(output, str) else None
    return _TurnResult(answer=answer, messages=result.all_messages())


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
    nudge = (
        f"Your previous response did not fully satisfy the request: {verdict.reason}. "
        "Correct it and complete what was asked."
    )
    # The range to drop on persist: the rejected ModelResponse (last message of
    # the original attempt) through the injected nudge ModelRequest (the first
    # new message of the correction) — two adjacent messages.
    clean_drop = (len(turn.messages) - 1, len(turn.messages))
    # One attempt only — no re-verify, so it cannot retry endlessly.
    corrected = await _drive_turn(
        run, agent, prompt=nudge, message_history=turn.messages, announced=announced
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


def build_chat_orchestrator(
    prompt: str,
    *,
    model: Model | None = None,
    model_role: str = "main",
    categories: Any = None,
    judge: Judge | None = None,
    store: ConversationStore | None = None,
    conversation_id: str | None = None,
) -> Orchestrator:
    """Build the orchestrator for one chat turn (one always-agent path).

    ``model`` overrides role resolution (tests, per-conversation picker);
    ``categories`` overrides the tool catalog and ``judge`` the verifier's judge.
    With ``store`` + ``conversation_id`` the turn continues prior history and
    persists its new messages; without them it runs stateless. The verifier only
    runs when enabled in settings (and, by default, only on tool-producing turns).
    """
    async def orchestrate(run: Run) -> None:
        settings = get_settings()
        resolved = model if model is not None else llm.resolve_model(model_role)
        agent = _build_agent(resolved, categories=categories)
        announced: set[str] = set()
        history = (
            await store.history(conversation_id)
            if store is not None and conversation_id is not None
            else None
        )
        start = len(history) if history else 0

        turn = await _drive_turn(
            run, agent, prompt=prompt, message_history=history, announced=announced
        )

        # Verify only a completed turn (not one parked for approval or stopped at
        # a bound), and only when the heuristic says it is worth judging.
        if (
            run.status is not RunStatus.awaiting_input
            and turn.answer is not None
            and settings.verify_enabled
            and _should_verify(settings, run)
        ):
            judging = judge or utility_judge
            turn = await _verify_and_correct(run, agent, prompt, turn, announced, judging)

        _finalize(
            run,
            turn,
            store=store,
            conversation_id=conversation_id,
            start=start,
            clean_drop=turn.clean_drop,
        )

    return orchestrate


def build_resume_orchestrator(
    parked: ParkedTurn, decisions: dict[str, Any], *, store: ConversationStore | None = None
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
        )
        _finalize(
            run,
            turn,
            store=store,
            conversation_id=parked.conversation_id,
            start=parked.persist_from,
            clean_drop=parked.clean_drop,
        )

    return orchestrate
