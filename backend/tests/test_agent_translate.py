"""The translation layer: Pydantic AI's node/event stream → our events."""

from __future__ import annotations

from pydantic_ai import Agent, FunctionToolResultEvent, RetryPromptPart
from pydantic_ai.models.test import TestModel

from agent import stream_agent_run
from agent.injections import AnnounceInjections
from agent.overhead import MeasureOverhead
from agent.translate import _on_tool_event
from runs import Run, RunStream, ViewLiveStopped
from tools.emit import RunEventEmitted


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
    _on_tool_event(event, run, None, None)

    failed = _first(run, "tool.failed")
    assert failed.name == "lookup"
    assert failed.tool_call_id == "c9"
    assert "bad input" in failed.error


async def test_a_parallel_batch_streams_every_call_independently():
    # Both tools requested in ONE assistant message, run concurrently. What must survive
    # is per-call identity: the transcript upserts by tool_call_id, so a batch that
    # blurred into one event would collapse into one card or misfile a result.
    agent = Agent(TestModel(custom_output_text="done"))

    @agent.tool_plain
    def alpha(q: str) -> str:
        return f"a:{q}"

    @agent.tool_plain
    def beta(q: str) -> str:
        return f"b:{q}"

    run = _run()
    async with agent.iter("use both") as agent_run:
        await stream_agent_run(agent_run, run)

    bodies = _bodies(run)
    started = [b for b in bodies if b.type == "tool.started"]
    completed = [b for b in bodies if b.type == "tool.completed"]

    assert {b.name for b in started} == {"alpha", "beta"}
    assert len({b.tool_call_id for b in started}) == 2
    # Both go out before either comes back — the shape a serial-only mapping can't make.
    order = [b.type for b in bodies if b.type in ("tool.started", "tool.completed")]
    assert order == ["tool.started", "tool.started", "tool.completed", "tool.completed"]
    # Each result is filed under the call that asked for it, not merged or swapped.
    assert {b.tool_call_id for b in completed} == {b.tool_call_id for b in started}

    # And the batch is ONE model round-trip: a second step only opens for the answer.
    assert len([b for b in bodies if b.type == "step.started"]) == 2


# ── What a tool and a capability say for themselves ──────────────────────────────
#
# Both used to reach through `ctx.deps` for the `Run` and call `run.emit`. They now
# emit into the library's own event stream and this translator lands them, which is
# what these cover: that the seam carries them at all, that a capability needs nothing
# of ours to use it, and that a tool's news arrives inside its own call rather than
# racing it.


async def test_a_tool_puts_its_own_news_on_the_stream():
    agent = Agent(TestModel(custom_output_text="done"))

    @agent.tool
    async def announce(ctx, note: str) -> str:
        await ctx.emit(RunEventEmitted(body=ViewLiveStopped(conversation_id=note)))
        return "ok"

    run = _run()
    async with agent.iter("say something") as agent_run:
        await stream_agent_run(agent_run, run)

    stopped = _first(run, "view.live.stopped")
    assert stopped.conversation_id
    # Inside its own call, not before it: the ordering the direct `run.emit` could not
    # promise, because a value written straight to the run is visible immediately while
    # the frame for the call it belongs to waits for the translator to reach it.
    order = [b.type for b in _bodies(run) if b.type.startswith(("tool.", "view."))]
    assert order == ["tool.started", "view.live.stopped", "tool.completed"]


async def test_the_capabilities_need_nothing_of_ours_to_report():
    """Neither capability touches `ctx.deps` any more, so both work on an agent that has
    none — which is the whole point of moving them onto the library's event seam, and the
    thing a mock of that seam would never catch."""

    def repo_instructions() -> str:
        return "CLAUDE.md says be brief."

    agent = Agent(
        TestModel(custom_output_text="done"),
        capabilities=[MeasureOverhead(), AnnounceInjections()],
    )
    agent.instructions(name="repo")(repo_instructions)

    run = _run()
    async with agent.iter("go") as agent_run:
        await stream_agent_run(agent_run, run)

    # The brief's named contributor was announced, once, with its text.
    injected = [b for b in _bodies(run) if b.type == "context.injected"]
    assert [(b.contributor, b.text) for b in injected] == [
        ("repo", "CLAUDE.md says be brief.")
    ]
    # And the request's non-conversation weight reached the run, where the gauge reads it.
    assert run.context_overhead is not None
    assert run.context_overhead.system >= len("CLAUDE.md says be brief.")
    assert any(block.id == "repo" for block in run.context_overhead.blocks)
