"""The code & shell tools: sandboxed execution (ungated), the fail-closed
degraded path, and the host escape hatch (approval-gated, with an explanation)."""

from __future__ import annotations

from pydantic_ai import Agent, DeferredToolRequests, ToolApproved
from pydantic_ai.models.test import TestModel

from agent import ParkedTurn, build_chat_orchestrator, build_resume_orchestrator, stream_agent_run
from runs import Run, RunRegistry, RunStatus, RunStream
from services.sandbox import SandboxResult, SandboxSpec
from tools import RunDeps, build_agent_toolsets
from tools.code import code_toolset


class FakeSession:
    """Records each spec it runs and returns a canned result."""

    def __init__(self) -> None:
        self.specs: list[SandboxSpec] = []

    async def run(self, spec: SandboxSpec) -> SandboxResult:
        self.specs.append(spec)
        return SandboxResult(exit_code=0, stdout="hello from box", stderr="")


class FakeSessionManager:
    """Hands out one session and remembers which key it was acquired under."""

    def __init__(self) -> None:
        self.session = FakeSession()
        self.acquired: str | None = None

    async def acquire(self, key: str) -> FakeSession:
        self.acquired = key
        return self.session


def _bodies(run: Run):
    return [e.body for e in run.stream.replay()]


async def _run_one_tool(tool: str, *, sessions=None) -> Run:
    """Drive a single code tool through an agent and return the finished Run."""
    agent = Agent(
        TestModel(call_tools=[tool]),
        deps_type=RunDeps,
        toolsets=build_agent_toolsets({"code": code_toolset()}),
        output_type=[str, DeferredToolRequests],
    )
    run = Run(id="t", kind="chat", owner_id="operator", stream=RunStream())
    deps = RunDeps(
        run=run, owner_id="operator", sandbox_sessions=sessions, conversation_id="conv-1"
    )
    async with agent.iter("go", deps=deps) as agent_run:
        await stream_agent_run(agent_run, run)
    return run


# --- sandboxed execution (the default, not approval-gated) -------------------
async def test_execute_code_runs_in_the_conversation_session():
    manager = FakeSessionManager()
    run = await _run_one_tool("code_execute_code", sessions=manager)

    # The session was keyed by the conversation (so follow-up calls reuse it).
    assert manager.acquired == "conv-1"
    # It ran in that session, with network off, via the python interpreter.
    assert len(manager.session.specs) == 1
    spec = manager.session.specs[0]
    assert spec.command[:2] == ["python", "-c"]
    assert spec.network is False
    # The result reached the model — no approval pause for a sandboxed call.
    completed = next(b for b in _bodies(run) if b.type == "tool.completed")
    assert completed.result["stdout"] == "hello from box"
    assert "approval.required" not in [b.type for b in _bodies(run)]


async def test_execute_code_fails_closed_without_a_runtime():
    # No sandbox wired in ⇒ the tool reports unavailable and does NOT touch host.
    run = await _run_one_tool("code_execute_code", sessions=None)
    completed = next(b for b in _bodies(run) if b.type == "tool.completed")
    assert "unavailable" in completed.result["error"].lower()


# --- host execution (the deliberate, approval-gated escape hatch) ------------
async def test_host_command_parks_with_an_explanation():
    reg = RunRegistry()
    orch = build_chat_orchestrator(
        "change the host",
        model=TestModel(call_tools=["code_run_host_command"]),
        categories={"code": code_toolset()},
    )
    run = reg.submit(kind="chat", owner_id="operator", orchestrator=orch)
    await run.wait()

    # It paused for approval instead of running on the host.
    assert run.status is RunStatus.awaiting_input
    approval = next(b for b in _bodies(run) if b.type == "approval.required")
    assert "run_host_command" in approval.name
    # The plain-language explanation rides as a distinct field for the operator.
    assert approval.explanation is not None
    assert "tool.completed" not in [b.type for b in _bodies(run)]


async def test_approved_host_command_runs_on_host():
    reg = RunRegistry()
    orch = build_chat_orchestrator(
        "change the host",
        model=TestModel(call_tools=["code_run_host_command"]),
        categories={"code": code_toolset()},
    )
    run = reg.submit(kind="chat", owner_id="operator", orchestrator=orch)
    await run.wait()
    parked: ParkedTurn = run.parked_payload
    call_id = parked.requests.approvals[0].tool_call_id

    # Approve with safe override args so the host path runs a harmless echo.
    safe = {"command": "echo HOSTRAN", "explanation": "x"}
    decision = {call_id: ToolApproved(override_args=safe)}
    await reg.resume(run.id, build_resume_orchestrator(parked, decision))
    await run.wait()

    assert run.status is RunStatus.done
    completed = next(b for b in _bodies(run) if b.type == "tool.completed")
    assert "HOSTRAN" in completed.result["stdout"]
