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
from runs import ApprovalRequired, LimitNotice, Orchestrator, Run, RunMetrics
from services import llm
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


@dataclass
class _TurnResult:
    """What one turn produced: a final answer (or None if it parked/blocked/hit
    a bound) and the message history needed to continue the conversation."""

    answer: str | None
    messages: list[ModelMessage] = field(default_factory=list)


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


async def _verify_and_correct(
    run: Run, agent: Agent, prompt: str, turn: _TurnResult, announced: set[str], judge: Judge
) -> None:
    """Judge the answer; on failure make a single bounded corrective re-attempt."""
    if not turn.answer or not turn.answer.strip():
        return  # nothing checkable to verify
    verdict = await judge(prompt, turn.answer)
    if verdict.ok:
        return
    run.emit(LimitNotice(limit="verify", message=f"re-attempting: {verdict.reason}"))
    nudge = (
        f"Your previous response did not fully satisfy the request: {verdict.reason}. "
        "Correct it and complete what was asked."
    )
    # One attempt only — no re-verify, so it cannot retry endlessly.
    await _drive_turn(run, agent, prompt=nudge, message_history=turn.messages, announced=announced)


def build_chat_orchestrator(
    prompt: str,
    *,
    model: Model | None = None,
    model_role: str = "main",
    categories: Any = None,
    judge: Judge | None = None,
) -> Orchestrator:
    """Build the orchestrator for one chat turn (one always-agent path).

    ``model`` overrides role resolution (tests, per-conversation picker);
    ``categories`` overrides the tool catalog and ``judge`` the verifier's judge
    (tests). The verifier only runs when enabled in settings.
    """

    async def orchestrate(run: Run) -> None:
        settings = get_settings()
        resolved = model if model is not None else llm.resolve_model(model_role)
        agent = _build_agent(resolved, categories=categories)
        announced: set[str] = set()
        turn = await _drive_turn(run, agent, prompt=prompt, announced=announced)
        if turn.answer is None:
            return  # parked for approval, blocked, or hit a bound
        if settings.verify_enabled:
            await _verify_and_correct(run, agent, prompt, turn, announced, judge or utility_judge)

    return orchestrate


def build_resume_orchestrator(parked: ParkedTurn, decisions: dict[str, Any]) -> Orchestrator:
    """Resume a parked turn with the operator's approve/deny decisions."""

    async def orchestrate(run: Run) -> None:
        results = DeferredToolResults(approvals=decisions)
        await _drive_turn(
            run,
            parked.agent,
            message_history=parked.message_history,
            deferred_results=results,
            announced=parked.announced,
        )

    return orchestrate
