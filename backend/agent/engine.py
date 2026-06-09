"""The agent engine — the first real orchestrator on the Run substrate.

Wraps Pydantic AI's ``Agent`` and drives it via ``agent.iter()`` so the chassis
can observe every step and stream it (translation lives in ``translate.py``).
The library owns the within-turn loop, tool selection, validation, and fallback;
we own the run lifecycle, the event stream, bounds, and — later — the meta-loop
(verifier/loop-break) and approval pause/resume (D20).

``build_chat_orchestrator`` returns an :data:`~runs.Orchestrator` ready to hand
to ``RunRegistry.submit`` — so a chat turn is just another Run (D5: single
always-agent path).
"""

from __future__ import annotations

from pydantic_ai import Agent, UsageLimitExceeded, UsageLimits
from pydantic_ai.models import Model

from core.config import get_settings
from runs import LimitNotice, Orchestrator, Run, RunMetrics
from services import llm

from .deps import RunDeps
from .translate import stream_agent_run


def build_chat_orchestrator(
    prompt: str,
    *,
    model: Model | None = None,
    model_role: str = "main",
) -> Orchestrator:
    """Build the orchestrator for one chat turn.

    ``model`` overrides role resolution (used by tests and the per-conversation
    model picker); otherwise the role is resolved from config (D16).
    """

    async def orchestrate(run: Run) -> None:
        settings = get_settings()
        resolved = model if model is not None else llm.resolve_model(model_role)
        agent = Agent(resolved, deps_type=RunDeps)
        deps = RunDeps(run=run, owner_id=run.owner_id)
        limits = UsageLimits(
            request_limit=settings.agent_request_limit,
            tool_calls_limit=settings.agent_tool_calls_limit,
        )
        try:
            async with agent.iter(prompt, deps=deps, usage_limits=limits) as agent_run:
                await stream_agent_run(agent_run, run)
                usage = agent_run.result.usage
                run.set_metrics(
                    RunMetrics(
                        steps=usage.requests,
                        tool_calls=usage.tool_calls,
                        input_tokens=usage.input_tokens,
                        output_tokens=usage.output_tokens,
                    )
                )
        except UsageLimitExceeded as exc:
            # AE-1.5/AE-1.6: hit a bound — stop and report state, don't error.
            run.emit(LimitNotice(limit="steps", message=str(exc)))
            run.block("usage limit reached")

    return orchestrate
