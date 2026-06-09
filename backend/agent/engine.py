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

from .translate import stream_agent_run


@dataclass
class ParkedTurn:
    """The continuation of a run parked awaiting approval. Opaque to the
    substrate; held on ``run.parked_payload`` and consumed by the approve route."""

    agent: Agent
    message_history: list[ModelMessage]
    requests: DeferredToolRequests
    announced: set[str] = field(default_factory=set)


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
) -> None:
    settings = get_settings()
    limits = UsageLimits(
        request_limit=settings.agent_request_limit,
        tool_calls_limit=settings.agent_tool_calls_limit,
    )
    deps = RunDeps(run=run, owner_id=run.owner_id)
    try:
        async with agent.iter(
            prompt,
            deps=deps,
            message_history=message_history,
            deferred_tool_results=deferred_results,
            usage_limits=limits,
        ) as agent_run:
            await stream_agent_run(agent_run, run, announced=announced)
            result = agent_run.result
    except UsageLimitExceeded as exc:
        # AE-1.5/AE-1.6: hit a bound — stop and report state, don't error.
        run.emit(LimitNotice(limit="steps", message=str(exc)))
        run.block("usage limit reached")
        return

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


def build_chat_orchestrator(
    prompt: str,
    *,
    model: Model | None = None,
    model_role: str = "main",
    categories: Any = None,
) -> Orchestrator:
    """Build the orchestrator for one chat turn (one always-agent path).

    ``model`` overrides role resolution (tests, per-conversation picker);
    ``categories`` overrides the tool catalog (tests).
    """

    async def orchestrate(run: Run) -> None:
        resolved = model if model is not None else llm.resolve_model(model_role)
        agent = _build_agent(resolved, categories=categories)
        await _drive_turn(run, agent, prompt=prompt, announced=set())

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
