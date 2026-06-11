"""The live-preview tools: start_preview emits preview.ready and forwards the
server spec to the session manager; a server that won't start feeds the failure
back without emitting an event; stop_preview emits preview.stopped. Degrades
gracefully when no sandbox is wired into the run."""

from __future__ import annotations

import json

from pydantic_ai import Agent, DeferredToolRequests
from pydantic_ai.models.function import DeltaToolCall, FunctionModel

from agent import stream_agent_run
from runs import Run, RunStream
from services.sandbox import PreviewHandle, SandboxError
from tools import RunDeps, build_agent_toolsets
from tools.preview import preview_toolset


class _FakeManager:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.started: list[tuple] = []
        self.stopped: list[str] = []

    async def start_preview(self, key: str, command: list[str], port: int) -> PreviewHandle:
        self.started.append((key, tuple(command), port))
        if self.fail:
            raise SandboxError("address already in use")
        return PreviewHandle(
            token="tok", container="c", host_port=5000,
            container_port=port, command=tuple(command),
        )

    async def stop_preview(self, key: str) -> None:
        self.stopped.append(key)


def _call_then_finish(tool_name: str, args: dict):
    """A model that calls one tool once, then answers with text."""

    def _tool_ran(messages) -> bool:
        return any(
            type(part).__name__ == "ToolReturnPart"
            for message in messages
            for part in message.parts
        )

    async def stream_fn(messages, info):
        if _tool_ran(messages):
            yield "done"
        else:
            yield {0: DeltaToolCall(name=tool_name, json_args=json.dumps(args))}

    return stream_fn


def _run(manager, *, tool_name, args, conversation_id="conv-1"):
    agent = Agent(
        FunctionModel(stream_function=_call_then_finish(tool_name, args)),
        deps_type=RunDeps,
        toolsets=build_agent_toolsets({"preview": preview_toolset()}),
        output_type=[str, DeferredToolRequests],
    )
    run = Run(id="r1", kind="chat", owner_id="operator", stream=RunStream())
    deps = RunDeps(
        run=run,
        owner_id="operator",
        sandbox_sessions=manager,
        conversation_id=conversation_id,
    )
    return agent, run, deps


def _bodies(run: Run):
    return [e.body for e in run.stream.replay()]


async def test_start_preview_emits_ready_and_forwards_spec():
    manager = _FakeManager()
    agent, run, deps = _run(
        manager,
        tool_name="preview_start_preview",
        args={"command": ["python", "-m", "http.server", "8000"], "port": 8000, "title": "Site"},
    )
    async with agent.iter("serve it", deps=deps) as agent_run:
        await stream_agent_run(agent_run, run)

    ready = next(b for b in _bodies(run) if b.type == "preview.ready")
    assert ready.url == "/previews/tok/"
    assert ready.port == 8000
    assert ready.command == "python -m http.server 8000"
    assert ready.title == "Site"
    assert ready.conversation_id == "conv-1"
    assert manager.started == [("conv-1", ("python", "-m", "http.server", "8000"), 8000)]


async def test_start_preview_failure_feeds_back_without_event():
    manager = _FakeManager(fail=True)
    agent, run, deps = _run(
        manager,
        tool_name="preview_start_preview",
        args={"command": ["bad"], "port": 8000},
    )
    async with agent.iter("serve it", deps=deps) as agent_run:
        await stream_agent_run(agent_run, run)

    assert "preview.ready" not in [b.type for b in _bodies(run)]
    assert manager.started  # it tried, and the error went back to the model as text


async def test_stop_preview_emits_stopped():
    manager = _FakeManager()
    agent, run, deps = _run(manager, tool_name="preview_stop_preview", args={})
    async with agent.iter("stop it", deps=deps) as agent_run:
        await stream_agent_run(agent_run, run)

    assert any(b.type == "preview.stopped" for b in _bodies(run))
    assert manager.stopped == ["conv-1"]


async def test_start_preview_unavailable_without_sandbox():
    agent, run, deps = _run(
        None, tool_name="preview_start_preview", args={"command": ["x"], "port": 8000}
    )
    async with agent.iter("serve it", deps=deps) as agent_run:
        await stream_agent_run(agent_run, run)

    assert "preview.ready" not in [b.type for b in _bodies(run)]
