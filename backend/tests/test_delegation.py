"""Delegation: two sub-agents, one coarse tool, bound per conversation.

Two assertions run through everything here.

**Rooting, not isolation.** `SubAgentToolset` defines no `for_run`, so the library hands
every run the same instance — and that instance is where the sub-agent's workspace root
and the event handler live. A test that only checked "two runs don't share mutable state"
would pass with both threads rooted at the same directory, which is precisely the bug.

**A worker works in a fork, and what comes back is a merge.** The fakes below are real
directories on both sides, so "the worker's file landed in the parent's workspace" is
asserted as a file rather than as a call that happened — the whole point of the fork is
what it does to files, and a stub that only records would pass with nothing copied.
"""

from __future__ import annotations

import json
import os
import shutil
from functools import partial
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai import RunContext, RunUsage
from pydantic_ai.exceptions import ApprovalRequired
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from pydantic_ai.models.test import TestModel

from core.container import ServiceContainer
from core.fork import MergeReport
from runs import Run, RunStream
from services.projects.repo import WorktreeState, branch_for, child_branch_for
from services.projects.store import ProjectStore
from services.projects.worktree import WorktreeManager
from services.registry import ModelRegistry
from services.sandbox import SandboxSessionManager
from services.workspace import RunWorkspace
from tests._helpers import client_app
from tools.agents import agents_toolset
from tools.delegation import (
    AGENT_NAME_ARG,
    AGENT_NAME_DESCRIPTION,
    DELEGATE_DESCRIPTION,
    DELEGATE_TOOL,
    EXPLORER,
    WORKER,
)
from tools.deps import RunDeps
from tools.shell import shell_toolset
from tools.worker import WORKER_BRIEF, child_toolsets

from .conftest import unfenced

OWNER = "operator"


class _FakeSession:
    def __init__(self, path: Path) -> None:
        self._path = path

    def ensure_workspace(self) -> Path:
        return self._path


class _FakeSessions:
    """`SandboxSessionManager`, as much of it as delegation touches.

    A fork is a copy and a merge back is a copy, both over real directories — see the
    module docstring for why they are not recorded calls.
    """

    def __init__(self, root: Path) -> None:
        self._root = root
        self.forked: list[tuple[str, str]] = []
        self.merged: list[tuple[str, str]] = []
        self.purged: list[str] = []

    def dir_for(self, key: str) -> Path:
        # A child key is `<parent>/w-xxxx`; flattened, or the fork would live *inside*
        # the workspace it was taken from and the merge back would walk itself.
        return self._root / key.replace("/", "-")

    def _made(self, key: str) -> Path:
        path = self.dir_for(key)
        path.mkdir(parents=True, exist_ok=True)
        return path

    async def acquire(self, key: str, *, holder: object = None) -> _FakeSession:
        return _FakeSession(self._made(key))

    async def fork(self, parent_key: str, child_key: str, *, holder: object = None):
        self.forked.append((parent_key, child_key))
        child = self._made(child_key)
        shutil.copytree(self._made(parent_key), child, dirs_exist_ok=True)
        return _FakeSession(child)

    async def merge_back(self, child_key: str, parent_key: str) -> MergeReport:
        self.merged.append((child_key, parent_key))
        return _copy_changed(self.dir_for(child_key), self._made(parent_key))

    async def purge(self, key: str) -> None:
        self.purged.append(key)
        shutil.rmtree(self.dir_for(key), ignore_errors=True)


class _FakeProjects:
    def __init__(self, root: Path) -> None:
        self._root = root

    async def get(self, owner_id: str, project_id: str):
        class _View:
            root_path = str(self._root)
            base_ref = "main"

        return _View()


class _FakeWorktrees:
    """`WorktreeManager`, the four calls a code-mode delegation makes of it."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self.forked: list[str] = []
        self.merged: list[str] = []
        self.discarded: list[str] = []

    def path_for(self, project_id: str) -> Path:
        path = self._root / project_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def child_for(self, project_id: str, conversation_id: str, delegation_id: str) -> Path:
        return self._root / f"{project_id}-{conversation_id}-{delegation_id}"

    async def acquire(self, *, project_id: str, root: Path, base_ref: str, conversation_id: str):
        return WorktreeState(
            path=self.path_for(project_id), branch=branch_for(conversation_id), base_ref=base_ref
        )

    async def fork(
        self, *, project_id: str, root: Path, conversation_id: str, delegation_id: str
    ) -> WorktreeState:
        self.forked.append(delegation_id)
        child = self.child_for(project_id, conversation_id, delegation_id)
        shutil.copytree(self.path_for(project_id), child, dirs_exist_ok=True)
        return WorktreeState(
            path=child,
            branch=child_branch_for(conversation_id, delegation_id),
            base_ref=branch_for(conversation_id),
        )

    async def merge_back(
        self, *, project_id: str, root: Path, conversation_id: str, delegation_id: str
    ) -> MergeReport:
        self.merged.append(delegation_id)
        return _copy_changed(
            self.child_for(project_id, conversation_id, delegation_id),
            self.path_for(project_id),
        )

    async def discard_child(
        self, *, project_id: str, root: Path, conversation_id: str, delegation_id: str
    ) -> None:
        self.discarded.append(delegation_id)


def _copy_changed(child: Path, parent: Path) -> MergeReport:
    """What a merge back does, in one line each way: land what differs, name it."""
    landed: list[str] = []
    for path in sorted(p for p in child.rglob("*") if p.is_file()):
        rel = str(path.relative_to(child))
        target = parent / rel
        if target.is_file() and target.read_bytes() == path.read_bytes():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        landed.append(rel)
    return MergeReport(merged=True, files=landed)


class _FakeResolved:
    def __init__(self, model) -> None:
        self.model = model
        self.reasoning_off = None


class _FakeRegistry:
    def __init__(self, model="test") -> None:
        self._model = model

    async def resolve_background(self, *, owner_id: str):
        return _FakeResolved(self._model)


def _scripted(*steps) -> FunctionModel:
    """A model that does one scripted thing per request.

    Each step is called with the messages so far and returns the parts of one response —
    which is what lets a step read a tool's return and put it in the report, the only way
    a sub-agent's *findings* reach the parent.

    Both halves are supplied because a sub-agent's progress is streamed onto the parent's
    run: passing an `event_stream_handler` is what makes every delegation a *streamed*
    request, and a model with no `stream_function` asserts rather than answering.
    """

    def parts(messages, info: AgentInfo):
        turn = sum(1 for message in messages if isinstance(message, ModelResponse))
        return steps[min(turn, len(steps) - 1)](messages, info)

    async def respond(messages, info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=parts(messages, info))

    async def stream(messages, info: AgentInfo):
        for part in parts(messages, info):
            if isinstance(part, TextPart):
                yield part.content
            else:
                yield {0: DeltaToolCall(name=part.tool_name, json_args=json.dumps(part.args))}

    return FunctionModel(respond, stream_function=stream)


def _reports(text: str) -> FunctionModel:
    """A sub-agent that calls nothing and reports one line."""
    return _scripted(lambda messages, info: [TextPart(text)])


def _returned(messages) -> str:
    """Everything the tools have returned so far, flattened."""
    return "\n".join(
        str(part.content)
        for message in messages
        for part in getattr(message, "parts", [])
        if isinstance(part, ToolReturnPart)
    )


def _deps(caps: ServiceContainer, conversation_id: str, **over) -> RunDeps:
    return RunDeps(
        run=Run(id=over.pop("run_id", "run-1"), kind="chat", owner_id=OWNER, stream=RunStream()),
        owner_id=OWNER,
        caps=caps,
        conversation_id=conversation_id,
        **over,
    )


def _ctx(caps: ServiceContainer, conversation_id: str, *, approved: bool = False, **over):
    ctx = RunContext(
        deps=_deps(caps, conversation_id, **over), model=TestModel(), usage=RunUsage()
    )
    # What the engine sets on the re-invocation after an approval; the gate below fires
    # once and then lets the delegation run.
    ctx.tool_call_approved = approved
    # The call a delegation's sub-agent ids are namespaced under. Set because it is the
    # half of the id that collides on a retry, which `TestSubagentEvents` asserts on.
    ctx.tool_call_id = "call-7"
    return ctx


@pytest.fixture
def emitted(monkeypatch) -> list[Any]:
    """Every body a delegation put on the run's stream, in order.

    Patched onto `RunContext` itself rather than onto one instance: the contexts built
    above are not backed by a running agent, so the real `emit` raises `UserError` — and
    the emission sites are all best-effort by design, so they would swallow precisely
    what is under test and every assertion would pass on an empty list.
    """
    seen: list[Any] = []

    async def emit(self, event):
        body = getattr(event, "body", None)
        if body is not None:
            seen.append(body)
        return event

    monkeypatch.setattr(RunContext, "emit", emit)
    return seen


def _of(bodies: list[Any], type_: str) -> list[Any]:
    return [b for b in bodies if getattr(b, "type", None) == type_]


async def _delegate(toolset, ctx, agent_name: str, task: str = "do the thing") -> str:
    return str(
        await toolset.call_tool(
            DELEGATE_TOOL, {AGENT_NAME_ARG: agent_name, "task": task}, ctx, None
        )
    )


def _sandbox_caps(
    tmp_path: Path, model="test", *, workspace: str = "conv-a"
) -> tuple[ServiceContainer, _FakeSessions]:
    """A sandbox conversation with a workspace already on disk, and its handles."""
    sessions = _FakeSessions(tmp_path / "sandbox")
    sessions.dir_for(workspace).mkdir(parents=True, exist_ok=True)
    caps = ServiceContainer()
    caps.add(_FakeRegistry(model), as_type=ModelRegistry)
    caps.add(sessions, as_type=SandboxSessionManager)
    return caps, sessions


# --- the binding is per conversation, per run ----------------------------------------


class _Ctx:
    """A stand-in RunContext for the binding tests. The `Run` is real because the binding
    is keyed on its id — a fake without one would let the run-scoping regression back in
    unnoticed."""

    def __init__(self, conversation_id: str, run_id: str) -> None:
        self.deps = RunDeps(
            run=Run(id=run_id, kind="chat", owner_id=OWNER, stream=RunStream()),
            owner_id=OWNER,
            caps=ServiceContainer(),
            conversation_id=conversation_id,
        )
        self.tool_call_id = "call-1"


def _bind_for(toolset, tmp_path, conversation_id: str, run_id: str = "run-1"):
    """The binding is what's under test, so it is reached directly rather than through
    a full delegate call (which would run a real sub-agent)."""
    return toolset._bind(  # noqa: SLF001
        str(tmp_path / conversation_id), _FakeResolved("test"), _Ctx(conversation_id, run_id)
    )


class TestBinding:
    async def test_two_conversations_get_different_workspace_roots(self, tmp_path):
        toolset = agents_toolset()
        a = _bind_for(toolset, tmp_path, "conv-a")
        b = _bind_for(toolset, tmp_path, "conv-b")

        # Not merely "different objects" — different *roots*. Sharing one would let a
        # sub-agent read another conversation's workspace.
        assert a is not b

    async def test_the_same_conversation_reuses_its_binding(self, tmp_path):
        toolset = agents_toolset()
        # Building one registers the sub-agents and generates their schemas; doing that
        # per call would be a real cost on a hot path.
        assert _bind_for(toolset, tmp_path, "conv-a") is _bind_for(toolset, tmp_path, "conv-a")

    async def test_a_second_run_gets_a_fresh_binding(self, tmp_path):
        toolset = agents_toolset()
        first = _bind_for(toolset, tmp_path, "conv-a", run_id="run-1")
        second = _bind_for(toolset, tmp_path, "conv-a", run_id="run-2")
        # The binding captures the run's event-stream handler, so reusing it across runs
        # would emit turn 2's sub-agent progress onto turn 1's finished Run — the
        # delegation would look silent from the second turn onward. Same workspace, same
        # model, different run ⇒ different binding.
        assert first is not second


class TestDegrades:
    async def test_no_registry_degrades_rather_than_failing_the_turn(self):
        result = await agents_toolset().call_tool(
            DELEGATE_TOOL,
            {AGENT_NAME_ARG: EXPLORER, "task": "look"},
            _ctx(ServiceContainer(), "conv-a"),
            None,
        )
        assert "unavailable" in str(result).lower()

    async def test_no_workspace_degrades_rather_than_failing_the_turn(self):
        caps = ServiceContainer()
        caps.add(_FakeRegistry(), as_type=ModelRegistry)
        result = await _delegate(agents_toolset(), _ctx(caps, "conv-a"), EXPLORER)
        assert "unavailable" in result.lower()


# --- the explorer: ungated, and read-only over the parent's own tree -------------------


class TestExplorer:
    async def test_it_reads_the_parents_workspace_and_cannot_write_to_it(self, tmp_path):
        def read(messages, info: AgentInfo):
            return [ToolCallPart("read_file", {"path": "note.txt"})]

        def report(messages, info: AgentInfo):
            offered = ",".join(sorted(tool.name for tool in info.function_tools))
            return [TextPart(f"{_returned(messages)}\ntools: {offered}")]

        caps, sessions = _sandbox_caps(tmp_path, _scripted(read, report))
        (sessions.dir_for("conv-a") / "note.txt").write_text("what the parent has\n")
        # Ungated: no approval is set on this call, and the explorer runs anyway.
        result = await _delegate(agents_toolset(), _ctx(caps, "conv-a"), EXPLORER)

        # Rooted at the *parent's* workspace — it read the file that only exists there.
        assert "what the parent has" in result
        # And read-only: the write tools are not among the ones it was offered, so there
        # is nothing for it to change even if it decided to.
        assert "read_file" in result
        assert "write_file" not in result
        assert "edit_file" not in result


# --- the worker: approved once, forked, merged back -----------------------------------


class TestWorkerIsGated:
    async def test_delegating_to_a_worker_without_approval_asks(self, tmp_path):
        caps, _sessions = _sandbox_caps(tmp_path)
        with pytest.raises(ApprovalRequired):
            await _delegate(agents_toolset(), _ctx(caps, "conv-a"), WORKER)

    async def test_the_gate_fires_before_anything_is_forked(self, tmp_path):
        caps, sessions = _sandbox_caps(tmp_path)
        with pytest.raises(ApprovalRequired):
            await _delegate(agents_toolset(), _ctx(caps, "conv-a"), WORKER)
        # Asking after a copy of the workspace had been taken would be a side effect the
        # operator never approved.
        assert sessions.forked == []

    async def test_the_delegate_tool_is_in_the_approval_vocabulary(self):
        async with client_app() as (client, _app):
            scopes = {row["name"] for row in (await client.get("/tools/approval-scopes")).json()}
        # Without this the operator is asked once per delegation and can never grant it
        # for the conversation.
        assert "agents_delegate_task" in scopes


class TestWorkerInASandbox:
    async def test_it_works_in_a_fork_and_its_work_is_merged_back(self, tmp_path):
        def write(messages, info: AgentInfo):
            return [ToolCallPart("write_file", {"path": "added.py", "content": "print(1)\n"})]

        def report(messages, info: AgentInfo):
            return [TextPart("I added added.py")]

        caps, sessions = _sandbox_caps(tmp_path, _scripted(write, report))
        parent = sessions.dir_for("conv-a")
        (parent / "note.txt").write_text("what the parent has\n")

        result = await _delegate(
            agents_toolset(), _ctx(caps, "conv-a", approved=True), WORKER
        )

        parent_key, child_key = sessions.forked[0]
        assert parent_key == "conv-a"
        assert child_key.startswith("conv-a/w-")
        # It wrote in its own copy, which was then merged back into the parent's
        # workspace — for real, as a file, not as a call that happened.
        assert (parent / "added.py").read_text() == "print(1)\n"
        assert sessions.merged == [(child_key, "conv-a")]
        # The hand-back is the worker's own report *and* what came of it.
        assert "I added added.py" in result
        assert "added.py" in result.split("Merged back into your workspace:")[1]
        # A fork is a whole second copy; nothing keeps one around.
        assert sessions.purged == [child_key]

    async def test_a_conflict_comes_back_named_rather_than_silently_dropped(self, tmp_path):
        caps, sessions = _sandbox_caps(tmp_path, _reports("done"))

        async def merge_back(child_key: str, parent_key: str) -> MergeReport:
            sessions.merged.append((child_key, parent_key))
            return MergeReport(merged=False, files=["a.py"], conflicts=["b.py"], deleted=["c.py"])

        sessions.merge_back = merge_back
        result = await _delegate(
            agents_toolset(), _ctx(caps, "conv-a", approved=True), WORKER
        )

        # Every outcome is named, because "three files conflicted" is not something the
        # agent reading this can act on.
        assert "a.py" in result
        assert "b.py" in result
        assert "c.py" in result
        # And it is not sent to compare versions: the fork goes away with the delegation
        # whichever way the merge went, so the worker's side of a conflict survives as
        # its report and nowhere else.
        assert "gone with the fork" in result
        assert sessions.purged == [sessions.forked[0][1]]

    async def test_a_worker_that_cannot_be_forked_merges_nothing_and_says_so(self, tmp_path):
        caps, sessions = _sandbox_caps(tmp_path)

        async def fork(parent_key, child_key, *, holder=None):
            raise RuntimeError("no runtime")

        sessions.fork = fork
        result = await _delegate(
            agents_toolset(), _ctx(caps, "conv-a", approved=True), WORKER
        )

        assert "no runtime" in result
        assert sessions.merged == []

    async def test_a_run_may_only_set_so_many_workers_going(self, tmp_path):
        caps, sessions = _sandbox_caps(tmp_path, _reports("done"))
        toolset = agents_toolset()
        ctx = _ctx(caps, "conv-a", approved=True)

        results = [await _delegate(toolset, ctx, WORKER) for _ in range(7)]

        # Each worker forks the whole workspace, so the budget is per run and the last
        # call is told to do the work itself rather than quietly running an eighth box.
        assert len(sessions.forked) == 6
        assert "limit" in results[-1]


class TestWorkerInACodeConversation:
    async def test_it_runs_commands_in_its_own_checkout_without_asking_again(
        self, tmp_path, monkeypatch
    ):
        worktrees = _FakeWorktrees(tmp_path / "worktrees")
        caps = ServiceContainer()
        caps.add(_FakeProjects(tmp_path / "project"), as_type=ProjectStore)
        caps.add(worktrees, as_type=WorktreeManager)

        def command(messages, info: AgentInfo):
            return [ToolCallPart("run_command", {"command": "echo ran > ran.txt"})]

        def report(messages, info: AgentInfo):
            return [TextPart("I ran it")]

        caps.add(_FakeRegistry(_scripted(command, report)), as_type=ModelRegistry)
        # The fence, faked at the one seam a test must not drive for real. Everything
        # else about the guard — the mode, the worktree, the approval — is the real one.
        monkeypatch.setattr(
            "tools.worker.shell_toolset", partial(shell_toolset, confiner=unfenced)
        )

        result = await _delegate(
            agents_toolset(),
            _ctx(caps, "conv-a", approved=True, mode="code", project_id="proj-1"),
            WORKER,
        )

        delegation_id = worktrees.forked[0]
        child = worktrees.child_for("proj-1", "conv-a", delegation_id)
        # The command really ran, in the child's own checkout: the shell's approval gate
        # let it through on `delegated_approved` rather than parking a run nobody is
        # watching, and the fenced shell was rooted at the fork.
        assert (child / "ran.txt").read_text().strip() == "ran"
        assert (worktrees.path_for("proj-1") / "ran.txt").read_text().strip() == "ran"
        assert worktrees.merged == [delegation_id]
        assert worktrees.discarded == [delegation_id]
        assert "I ran it" in result

    async def test_what_it_left_running_is_stopped_when_the_delegation_ends(
        self, tmp_path, monkeypatch
    ):
        """A worker that never calls `stop_command` still leaves nothing behind.

        Its background processes are started in sessions of their own, and the ids they
        would be stopped by live only in the child's transcript — so a server it forgot
        would hold its port forever, writing into a checkout that the discard is about to
        remove out from under it.
        """
        worktrees = _FakeWorktrees(tmp_path / "worktrees")
        caps = ServiceContainer()
        caps.add(_FakeProjects(tmp_path / "project"), as_type=ProjectStore)
        caps.add(worktrees, as_type=WorktreeManager)
        pid_file = tmp_path / "pid"

        def start(messages, info: AgentInfo):
            return [
                ToolCallPart("start_command", {"command": f"echo $$ > {pid_file}; sleep 300"})
            ]

        # Waits for the spawn rather than assuming it: the pid is what gets asserted on.
        wait = f"for _ in $(seq 100); do [ -s {pid_file} ] && break; sleep 0.05; done"

        def settle(messages, info: AgentInfo):
            return [ToolCallPart("run_command", {"command": wait})]

        def report(messages, info: AgentInfo):
            return [TextPart("started it and forgot about it")]

        caps.add(_FakeRegistry(_scripted(start, settle, report)), as_type=ModelRegistry)
        monkeypatch.setattr(
            "tools.worker.shell_toolset", partial(shell_toolset, confiner=unfenced)
        )

        await _delegate(
            agents_toolset(),
            _ctx(caps, "conv-a", approved=True, mode="code", project_id="proj-1"),
            WORKER,
        )

        pid = int(pid_file.read_text().strip())
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


class TestWhatAChildCannotDo:
    def _child_ctx(self, tmp_path: Path, *, delegated: bool):
        workspace = RunWorkspace(root=tmp_path, kind="sandbox", files=None)
        deps = _deps(ServiceContainer(), "conv-a", delegated_approved=delegated)
        deps.workspace = workspace
        return RunContext(deps=deps, model=TestModel(), usage=RunUsage()), workspace

    async def _offered(self, tmp_path: Path, *, delegated: bool) -> set[str]:
        ctx, workspace = self._child_ctx(tmp_path, delegated=delegated)
        names: set[str] = set()
        for toolset in child_toolsets(workspace):
            names |= set(await toolset.get_tools(ctx))
        return names

    async def test_it_cannot_ask_the_operator_anything(self, tmp_path):
        """The two tools that end in a question are withheld from a delegated run.

        There is nobody on the other side of a worker: the conversation belongs to the
        agent that delegated to it, and a question raised here would end the child's run
        on a deferred call no one will ever settle. What it could not reach goes in its
        report instead, which is where the parent — who *can* ask — reads it.
        """
        child = await self._offered(tmp_path, delegated=True)
        parent = await self._offered(tmp_path, delegated=False)

        assert {"request_egress", "run_host_command"} <= parent
        assert not {"request_egress", "run_host_command"} & child
        # It still has its own machine to compute on, and its own copy to edit.
        assert {"execute", "write_file", "read_file"} <= child
        # And it is told to hand the question upwards rather than stall on it.
        assert "report" in WORKER_BRIEF


# --- what a delegation says about itself on the stream ---------------------------------


class TestSubagentEvents:
    """A delegation reports itself twice, on purpose.

    The flattened `tool.progress` line is what the transcript reads: one sentence under
    the call that made it. The `subagent.*` frames are what a roster of sub-agents reads:
    which one is running, what it was asked, how it ended. Neither is derivable from the
    other — every delegation on one tool call flattens onto the same `tool_call_id` — so
    the assertions below pin *both* being emitted, not one replacing the other.
    """

    async def test_a_delegation_opens_and_closes_a_sub_agent(self, tmp_path, emitted):
        caps, _sessions = _sandbox_caps(tmp_path, _reports("I read the file"))

        result = await _delegate(agents_toolset(), _ctx(caps, "conv-a"), EXPLORER, "look around")

        (started,) = _of(emitted, "subagent.started")
        assert started.agent_name == EXPLORER
        # The task, verbatim: a row that cannot say what was asked is a spinner.
        assert started.task == "look around"
        assert started.tool_call_id == "call-7"
        # Namespaced by run *and* call, so two conversations cannot collide on one row.
        assert started.subagent_id.startswith("run-1:call-7:")

        (completed,) = _of(emitted, "subagent.completed")
        assert completed.subagent_id == started.subagent_id
        assert "I read the file" in completed.summary
        assert completed.duration_ms >= 0
        # And the report the frames describe is still what the model got back.
        assert "I read the file" in result
        assert _of(emitted, "subagent.failed") == []

    async def test_the_flattened_transcript_line_still_goes_out(self, tmp_path, emitted):
        """The whole point of the pair: this is not a migration.

        A sub-agent's events reach the transcript as one line of prose under the
        delegating call, and reach the roster as `subagent.progress` filed under the
        sub-agent that said it. Dropping either leaves one of the two surfaces blind.
        """
        caps, _sessions = _sandbox_caps(tmp_path, _reports("done"))

        await _delegate(agents_toolset(), _ctx(caps, "conv-a"), EXPLORER)

        flattened = _of(emitted, "tool.progress")
        structured = _of(emitted, "subagent.progress")
        assert flattened, "the transcript's one-liner must survive"
        assert structured, "the roster's per-sub-agent line must exist"
        # Same events, same words — filed two ways.
        assert [b.partial for b in flattened] == [b.partial for b in structured]
        assert all(line.startswith(f"{EXPLORER}: ") for line in (b.partial for b in structured))
        (started,) = _of(emitted, "subagent.started")
        assert {b.subagent_id for b in structured} == {started.subagent_id}

    async def test_a_retried_delegation_is_a_second_sub_agent(self, tmp_path, emitted):
        """The model re-issuing a delegation reuses its `tool_call_id`.

        Keyed on that alone the two runs would fold into one row that started twice and
        finished twice; the sequence is what keeps them apart.
        """
        caps, _sessions = _sandbox_caps(tmp_path, _reports("done"))
        toolset, ctx = agents_toolset(), _ctx(caps, "conv-a")

        await _delegate(toolset, ctx, EXPLORER)
        await _delegate(toolset, ctx, EXPLORER)

        ids = [b.subagent_id for b in _of(emitted, "subagent.started")]
        assert len(ids) == 2
        assert len(set(ids)) == 2
        assert all(i.startswith("run-1:call-7:") for i in ids)
        # Each close names its own opener, or the second row never stops spinning.
        assert [b.subagent_id for b in _of(emitted, "subagent.completed")] == ids

    async def test_a_sub_agent_that_raises_still_reports(self, tmp_path, emitted, monkeypatch):
        """The failure case is the one a row would otherwise sit on forever.

        A delegation's ordinary failures degrade to a sentence for the model, so anything
        that actually escapes is unusual — and the close is in a `finally` for exactly
        that: the exception reaches the turn untouched, and the row still ends.
        """
        caps, _sessions = _sandbox_caps(tmp_path)

        async def boom(*args, **kwargs):
            raise RuntimeError("the fork went away")

        monkeypatch.setattr("tools.agents.run_worker", boom)

        with pytest.raises(RuntimeError):
            await _delegate(agents_toolset(), _ctx(caps, "conv-a", approved=True), WORKER)

        (started,) = _of(emitted, "subagent.started")
        assert started.agent_name == WORKER
        (failed,) = _of(emitted, "subagent.failed")
        assert failed.subagent_id == started.subagent_id
        assert "the fork went away" in failed.error
        assert _of(emitted, "subagent.completed") == []

    async def test_a_delegation_that_never_happens_opens_no_row(self, tmp_path, emitted):
        """Degrading before anything is delegated is not a sub-agent.

        `delegate_task` answers "unavailable" for a missing registry or workspace the same
        way every capability-backed tool degrades. A row opened for one would name a
        sub-agent that never existed and never close.
        """
        await _delegate(agents_toolset(), _ctx(ServiceContainer(), "conv-a"), EXPLORER)

        assert _of(emitted, "subagent.started") == []


# --- what the model and the operator are told -----------------------------------------


class TestCatalogAndPrompt:
    async def test_the_delegate_tool_is_operator_toggleable(self):
        async with client_app() as (_client, app):
            # The whole reason it is a toolset rather than a capability: it has to be in
            # the catalog the operator can switch off.
            assert "agents" in app.state.tool_categories
            assert DELEGATE_TOOL in set(app.state.tool_categories["agents"].tools)

    def test_the_roster_names_both_sub_agents_and_says_when_not_to_delegate(self):
        """It used to be a second standing instruction at the prompt head saying what the
        description already implies. One home, read where the model is deciding."""
        text = agents_toolset().tools[DELEGATE_TOOL].description or ""
        assert text == DELEGATE_DESCRIPTION
        assert EXPLORER in text
        assert WORKER in text
        # The difference between them is the only thing that lets the model pick.
        assert "changing nothing" in text
        assert "merged back" in text
        # It must also say when *not* to delegate, or the model reaches for it on
        # one-tool-call questions and pays a round trip for nothing.
        assert "not delegate" in text.lower()

    async def test_the_operator_is_shown_what_the_model_is_told(self):
        """The description is read from two places — `get_tools` for the model, `.tools`
        for the catalog — and an override applied to one of them is a settings screen
        describing a tool that no longer works that way."""
        toolset = agents_toolset()
        offered = await toolset.get_tools(_ctx(ServiceContainer(), "conv-a"))
        assert offered[DELEGATE_TOOL].tool_def.description == (
            toolset.tools[DELEGATE_TOOL].description
        )

    async def test_the_agent_name_parameter_points_at_the_roster_that_exists(self):
        """The harness writes `agent_name` against the standing listing its capability
        form registers. We register the toolset and put the roster in the description, so
        the library's text sends the model looking for a listing nothing writes — it then
        guesses a name and spends a retry on `Unknown sub-agent`."""
        offered = await agents_toolset().get_tools(_ctx(ServiceContainer(), "conv-a"))
        schema = offered[DELEGATE_TOOL].tool_def.parameters_json_schema
        assert schema["properties"][AGENT_NAME_ARG]["description"] == AGENT_NAME_DESCRIPTION
