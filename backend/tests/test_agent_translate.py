"""The translation layer: Pydantic AI's node/event stream → our events."""

from __future__ import annotations

from pydantic_ai import Agent, FunctionToolResultEvent, RetryPromptPart
from pydantic_ai.models.test import TestModel

from agent import stream_agent_run
from agent.translate import _on_tool_event
from runs import Run, RunStream


def _run() -> Run:
    return Run(id="t", kind="chat", owner_id="operator", stream=RunStream())


def _bodies(run: Run):
    return [e.body for e in run.stream.replay()]


def _first(run: Run, type_name: str):
    return next(b for b in _bodies(run) if b.type == type_name)


async def test_translates_steps_text_and_tool_calls():
    agent = Agent(TestModel(custom_output_text="all done"))

    @agent.tool_plain
    def add(a: int, b: int) -> int:
        return a + b

    run = _run()
    async with agent.iter("add two numbers") as agent_run:
        await stream_agent_run(agent_run, run)

    types = [b.type for b in _bodies(run)]
    assert "step.started" in types and "step.completed" in types
    assert "tool.started" in types and "tool.completed" in types
    assert "answer.delta" in types

    started = _first(run, "tool.started")
    assert started.name == "add"
    assert set(started.args) == {"a", "b"}

    completed = _first(run, "tool.completed")
    assert completed.result == started.args["a"] + started.args["b"]

    answer = "".join(b.text for b in _bodies(run) if b.type == "answer.delta")
    assert answer == "all done"


async def test_retry_prompt_part_becomes_tool_failed():
    # A tool retry/error (RetryPromptPart) maps to tool.failed, not a crash.
    run = _run()
    event = FunctionToolResultEvent(
        part=RetryPromptPart(content="bad input", tool_name="lookup", tool_call_id="c9")
    )
    _on_tool_event(event, run)

    failed = _first(run, "tool.failed")
    assert failed.name == "lookup"
    assert failed.tool_call_id == "c9"
    assert "bad input" in failed.error
