"""The toolset access-policy stack: namespacing, the enabled gate, deps reach."""

from __future__ import annotations

from pydantic_ai import Agent, DeferredToolRequests, FunctionToolset, RunContext
from pydantic_ai.models.test import TestModel

from agent import stream_agent_run
from runs import Run, RunStream
from tools import RunDeps, build_agent_toolsets


def _run() -> Run:
    return Run(id="t", kind="chat", owner_id="operator", stream=RunStream())


async def _run_agent(*, disabled=frozenset(), categories=None) -> Run:
    agent = Agent(
        TestModel(custom_output_text="ok"),
        deps_type=RunDeps,
        toolsets=build_agent_toolsets(categories),
        # The default catalog includes an approval-gated tool (host exec); accept
        # DeferredToolRequests like the real engine so it defers instead of erroring.
        output_type=[str, DeferredToolRequests],
    )
    run = _run()
    deps = RunDeps(run=run, owner_id="operator", disabled_tools=disabled)
    async with agent.iter("go", deps=deps) as agent_run:
        await stream_agent_run(agent_run, run)
    return run


def _tool_names(run: Run) -> list[str]:
    return [e.body.name for e in run.stream.replay() if e.body.type == "tool.started"]


async def test_builtin_tool_is_namespaced_and_invoked():
    names = _tool_names(await _run_agent())
    assert any("builtin" in n and "now" in n for n in names)


async def test_disabled_tool_is_not_offered():
    name = next(n for n in _tool_names(await _run_agent()) if "now" in n)
    run = await _run_agent(disabled=frozenset({name}))
    assert name not in _tool_names(run)


async def test_deps_reach_tools():
    seen: dict[str, str] = {}
    toolset: FunctionToolset[RunDeps] = FunctionToolset()

    @toolset.tool
    def whoami(ctx: RunContext[RunDeps]) -> str:
        seen["owner"] = ctx.deps.owner_id
        return ctx.deps.owner_id

    await _run_agent(categories={"id": toolset})
    assert seen.get("owner") == "operator"
