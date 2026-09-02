"""The code & shell tools: sandboxed execution, the fail-closed degraded path, and the
host escape hatch (approval-gated on the tool itself, with an explanation).

Running a program reaches past every permission level's write scope, so a call to either
runner is deferred before it executes (`services/permissions`) — the helper below approves
and continues, because what these tests are about is what the tool does once it runs."""

from __future__ import annotations

from pydantic_ai import Agent, DeferredToolRequests, DeferredToolResults, ToolApproved
from pydantic_ai.models.test import TestModel

from agent import ParkedTurn, build_chat_orchestrator, build_resume_orchestrator, stream_agent_run
from core.config import Settings
from core.container import ServiceContainer
from runs import Run, RunRegistry, RunStatus, RunStream
from services.sandbox import SandboxError, SandboxResult, SandboxSessionManager, SandboxSpec
from tools import RunDeps, build_agent_toolsets
from tools import code as code_module
from tools.code import code_toolset


class _CannedSession:
    """A session that returns a preset result or raises a preset error."""

    is_warm = False

    def __init__(self, *, result: SandboxResult | None = None, error: Exception | None = None):
        self._result = result
        self._error = error

    async def run(self, spec: SandboxSpec) -> SandboxResult:
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result


class _CannedManager:
    def __init__(self, session: _CannedSession) -> None:
        self._session = session

    async def acquire(self, key: str, *, holder: object = None) -> _CannedSession:
        return self._session


class FakeSession:
    """Records each spec it runs and returns a canned result."""

    is_warm = False

    def __init__(self) -> None:
        self.specs: list[SandboxSpec] = []

    async def run(self, spec: SandboxSpec) -> SandboxResult:
        self.specs.append(spec)
        return SandboxResult(exit_code=0, stdout="hello from box", stderr="")


class FakeSessionManager:
    """Hands out one session and remembers which key — and which run — it was acquired
    under."""

    def __init__(self) -> None:
        self.session = FakeSession()
        self.acquired: str | None = None
        self.holder: object = None

    async def acquire(self, key: str, *, holder: object = None) -> FakeSession:
        self.acquired = key
        self.holder = holder
        return self.session


def _bodies(run: Run):
    return [e.body for e in run.stream.replay()]


def _one_tool_agent(tool: str) -> Agent:
    return Agent(
        TestModel(call_tools=[tool]),
        deps_type=RunDeps,
        toolsets=build_agent_toolsets({"code": code_toolset()}),
        output_type=[str, DeferredToolRequests],
    )


def _one_tool_deps(run: Run, sessions) -> RunDeps:
    caps = ServiceContainer()
    if sessions is not None:
        # The fake manager registers under the class the code tools resolve.
        caps.add(sessions, as_type=SandboxSessionManager)
    return RunDeps(run=run, owner_id="operator", caps=caps, conversation_id="conv-1")


async def _run_one_tool(tool: str, *, sessions=None) -> Run:
    """Drive a single code tool through an agent and return the finished Run.

    Two passes, because running a program reaches past every permission level's write
    scope: the first pass comes back with the call deferred rather than executed, and the
    second supplies the approval the operator would give. These tests are about what the
    tool *does* once it runs, so the helper approves and carries on — the same two steps
    the approve route drives in production, with one `announced` set across both so a
    deferred call is still announced exactly once.
    """
    agent = _one_tool_agent(tool)
    run = Run(id="t", kind="chat", owner_id="operator", stream=RunStream())
    deps = _one_tool_deps(run, sessions)
    announced: set[str] = set()
    async with agent.iter("go", deps=deps) as agent_run:
        await stream_agent_run(agent_run, run, announced=announced)
        output = agent_run.result.output
        messages = agent_run.result.all_messages()
    if not isinstance(output, DeferredToolRequests) or not output.approvals:
        return run
    approvals = {call.tool_call_id: ToolApproved() for call in output.approvals}
    async with agent.iter(
        None,
        deps=deps,
        message_history=messages,
        deferred_tool_results=DeferredToolResults(approvals=approvals),
    ) as agent_run:
        await stream_agent_run(agent_run, run, announced=announced)
    return run


# --- sandboxed execution (contained, and still the level's to permit) --------
async def test_sandboxed_execution_is_deferred_before_it_runs():
    """The container is a fence around the blast radius, not a reason to treat running
    arbitrary code as a workspace write — so the working permission level defers the call
    and the operator (or, at Auto, the review) says whether it happens."""
    manager = FakeSessionManager()
    agent = _one_tool_agent("code_execute")
    run = Run(id="t", kind="chat", owner_id="operator", stream=RunStream())
    async with agent.iter("go", deps=_one_tool_deps(run, manager)) as agent_run:
        await stream_agent_run(agent_run, run)
        output = agent_run.result.output

    assert isinstance(output, DeferredToolRequests)
    assert [c.tool_name for c in output.approvals] == ["code_execute"]
    assert manager.session.specs == []  # requested, not executed


async def test_execute_code_runs_in_the_conversation_session():
    manager = FakeSessionManager()
    run = await _run_one_tool("code_execute", sessions=manager)

    # The session was keyed by the conversation (so follow-up calls reuse it) and claimed
    # by the run, so the live-session cap cannot displace the container between this call
    # and the next one — the seal drops `node_modules`, `.venv` and `.git` by design.
    assert manager.acquired == "conv-1"
    assert manager.holder is run
    # It ran in that session, with network off, via the python interpreter.
    assert len(manager.session.specs) == 1
    spec = manager.session.specs[0]
    assert spec.command[:2] == ["python", "-c"]
    assert spec.network is False
    # The result reached the model, once the call was approved.
    completed = next(b for b in _bodies(run) if b.type == "tool.completed")
    assert completed.result["stdout"] == "hello from box"
    # Announced once across both passes, not re-announced on the continuation.
    assert len([b for b in _bodies(run) if b.type == "tool.started"]) == 1


async def test_cold_session_announces_the_spin_up():
    # A cold container emits a tool.progress so the wait reads as the environment
    # starting up, not the model stalling.
    manager = FakeSessionManager()  # FakeSession.is_warm is False ⇒ cold start
    run = await _run_one_tool("code_execute", sessions=manager)

    progress = [b for b in _bodies(run) if b.type == "tool.progress"]
    assert len(progress) == 1
    assert "sandbox" in progress[0].partial.lower()


async def test_cold_session_announces_a_download_when_the_image_is_still_pulling():
    # sandbox-01: distinguishes an ordinary cold start from one that's actually
    # waiting on the boot-time image pull, so the wait reads truthfully.
    class WarmingSessionManager(FakeSessionManager):
        image_warmup_pending = True

    manager = WarmingSessionManager()
    run = await _run_one_tool("code_execute", sessions=manager)

    progress = [b for b in _bodies(run) if b.type == "tool.progress"]
    assert len(progress) == 1
    assert "download" in progress[0].partial.lower()


async def test_execute_code_fails_closed_without_a_runtime():
    # No sandbox wired in ⇒ the tool reports unavailable and does NOT touch host.
    run = await _run_one_tool("code_execute", sessions=None)
    completed = next(b for b in _bodies(run) if b.type == "tool.completed")
    assert completed.result["ok"] is False
    assert "unavailable" in completed.result["error"].lower()


# --- failures feed back to the model (the iterate-fix loop) -------------------
async def _run_canned(*, result=None, error=None) -> dict:
    manager = _CannedManager(_CannedSession(result=result, error=error))
    run = await _run_one_tool("code_execute", sessions=manager)
    return next(b for b in _bodies(run) if b.type == "tool.completed").result


async def test_failed_run_feeds_stderr_and_a_hint_back():
    failing = SandboxResult(exit_code=1, stdout="", stderr="Traceback: NameError: x")
    result = await _run_canned(result=failing)
    assert result["ok"] is False
    assert "NameError" in result["stderr"]  # the real error reaches the model
    assert "non-zero" in result["error"]  # plus a plain-language hint


async def test_timeout_and_oom_get_legible_hints():
    timed = SandboxResult(exit_code=124, stdout="", stderr="", timed_out=True)
    assert "time limit" in (await _run_canned(result=timed))["error"]

    killed = SandboxResult(exit_code=137, stdout="", stderr="")  # SIGKILL, empty stderr
    assert "memory" in (await _run_canned(result=killed))["error"]


async def test_sandbox_failure_feeds_back_instead_of_crashing_the_run():
    # A SandboxError (container won't start, damaged seal, …) becomes a result the
    # model can act on — the run completes, it does not error out.
    result = await _run_canned(error=SandboxError("container would not start"))
    assert result["ok"] is False
    assert "container would not start" in result["error"]


# --- sandbox-07: failure hints name the actual configured cap ----------------


async def test_sigsegv_hint_is_distinguished_from_oom_and_pid_cap():
    crashed = SandboxResult(exit_code=139, stdout="", stderr="")
    hint = (await _run_canned(result=crashed))["error"]
    assert "139" in hint and "SIGSEGV" in hint
    assert "memory" not in hint.lower()
    assert "processes/threads" not in hint


async def test_memory_hint_names_the_actual_configured_cap(monkeypatch):
    monkeypatch.setattr(code_module, "get_settings", lambda: Settings(sandbox_memory="777m"))
    killed = SandboxResult(exit_code=137, stdout="", stderr="")
    hint = (await _run_canned(result=killed))["error"]
    assert "777m" in hint


async def test_pid_cap_hint_is_distinguished_from_plain_nonzero(monkeypatch):
    monkeypatch.setattr(code_module, "get_settings", lambda: Settings(sandbox_pids_limit=64))
    stderr = "OSError: [Errno 11] Resource temporarily unavailable: fork failed"
    failing = SandboxResult(exit_code=1, stdout="", stderr=stderr)
    hint = (await _run_canned(result=failing))["error"]
    assert "processes/threads" in hint
    assert "64" in hint  # the actual configured pids_limit, not a guess


async def test_missing_module_hint_states_the_exact_install_mechanics():
    # The failure mode this guards: the model knows it must install but botches
    # the mechanics (network=True inside the code string, hallucinated pip flags).
    # The hint states the exact next call, including that `network` is a tool
    # argument, not part of the command.
    stderr = (
        "Traceback (most recent call last):\n"
        '  File "<string>", line 1, in <module>\n'
        "ModuleNotFoundError: No module named 'matplotlib'\n"
    )
    failing = SandboxResult(exit_code=1, stdout="", stderr=stderr)
    hint = (await _run_canned(result=failing))["error"]
    assert "pip install matplotlib" in hint
    assert "network=True" in hint
    assert "not part of the command" in hint


async def test_offline_fetch_hint_points_at_the_network_tool_argument():
    # A pip/fetch attempt without egress fails with resolution errors; the hint
    # names the `network=True` tool argument as the fix (the run had network off).
    stderr = (
        "WARNING: Retrying... Temporary failure in name resolution\n"
        "ERROR: No matching distribution found for matplotlib\n"
    )
    failing = SandboxResult(exit_code=1, stdout="", stderr=stderr)
    hint = (await _run_canned(result=failing))["error"]
    assert "network=True" in hint
    assert "argument" in hint


async def test_fallback_hint_points_at_the_stream_that_holds_the_error():
    # Some runtimes print their error to stdout with an empty stderr — "see
    # stderr" would send the model looking at nothing.
    stdout_only = SandboxResult(exit_code=128, stdout="something exploded", stderr="")
    hint = (await _run_canned(result=stdout_only))["error"]
    assert "stdout" in hint

    silent = SandboxResult(exit_code=3, stdout="", stderr="")
    hint = (await _run_canned(result=silent))["error"]
    assert "no output" in hint


async def test_execute_description_states_the_live_config_caps(monkeypatch):
    settings = Settings(
        sandbox_memory="256m",
        sandbox_cpus="0.5",
        sandbox_pids_limit=64,
    )
    monkeypatch.setattr(code_module, "get_settings", lambda: settings)

    description = code_module.code_toolset().tools["execute"].description

    assert "256m" in description
    assert "0.5" in description
    assert "64" in description
    # The resource caps are real and worth stating; there is no output cap to state.
    assert "come back whole" in description


async def test_execute_points_at_the_file_tools_without_reciting_them():
    """The catalog already hands the model every `files_*` tool with its own description;
    naming all six again here bought a second copy of that text on every turn. What the
    model cannot get elsewhere — that those tools reach *this* directory — is one
    sentence."""
    description = code_module.code_toolset().tools["execute"].description

    assert "files_*" in description
    for recited in ("files_read_file", "files_edit_file", "files_list_directory"):
        assert recited not in description
    # The machine itself is still described only here.
    assert "/work" in description and "pip" in description


# --- output is returned whole ------------------------------------------------


async def test_output_is_returned_whole(monkeypatch):
    # The blanket per-stream cap is gone. It fired on every run regardless of context
    # pressure and cost the model the middle of exactly the output it had just asked
    # for; the turn's own context-overflow stop is what catches a pathological run.
    monkeypatch.setattr(code_module, "get_settings", Settings)
    big = "".join(f"{i:04d}\n" for i in range(10_000))  # 50,000 chars
    result = await _run_canned(result=SandboxResult(exit_code=0, stdout=big, stderr="world"))
    assert result["stdout"] == big
    assert result["stderr"] == "world"
    assert "elided" not in result["stdout"]


async def test_host_command_output_is_returned_whole():
    # run_host_command shares `_exec_result`, so it gets the same untrimmed output.
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
    big_echo = "x" * 20_000  # comfortably over what the retired cap would have trimmed
    decision = {
        call_id: ToolApproved(override_args={"command": f"echo {big_echo}", "explanation": "x"})
    }
    await reg.resume(run.id, build_resume_orchestrator(parked, decision))
    await run.wait()

    completed = next(b for b in _bodies(run) if b.type == "tool.completed")
    assert completed.result["stdout"].strip() == big_echo


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
