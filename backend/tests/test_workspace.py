"""One workspace per run, resolved once.

The bug this file exists to catch is not "the file tools point at the wrong directory" —
that would be obvious. It is the agent **editing a file it cannot run**: file tools rooted
at a worktree while attachments stage into a container, or a skill's scripts announced at
`/work/...` in a conversation whose shell runs on the host. Every subsystem that used to
assume "the workspace is the sandbox" has to come out of the same resolver, so the tests
below assert the *agreement* between them rather than each one in isolation.

The other assertion worth naming: **rooting, not isolation**. Two conversations having
different `Shell` state is satisfied by the library's own `for_run` with both of them
rooted at the same path — which is exactly the bug. So the roots are compared to the
worktrees they should be, not merely to each other.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

import services.sandbox.host as host_module
import tools.shell as shell_module
from core.config import Settings
from core.container import ServiceContainer
from runs import Run, RunStream
from services.projects import ProjectStore, WorktreeManager
from services.sandbox import HostConfinement, SandboxError, SandboxSessionManager
from services.workspace import (
    SANDBOX_MOUNT,
    WORKTREE_SCRATCH,
    HostFiles,
    RunWorkspace,
    resolve_workspace,
)
from tools.deps import RunDeps
from tools.shell import shell_toolset
from tools.workspace import run_workspace

OWNER = "operator"


# --- fakes: the two capabilities the resolver reaches for ----------------------------


class _FakeSession:
    def __init__(self, path: Path) -> None:
        self._path = path

    def ensure_workspace(self) -> Path:
        return self._path

    def read_file(self, relpath: str) -> bytes:
        return (self._path / relpath).read_bytes()

    def write_file(self, relpath: str, content: bytes) -> None:
        target = self._path / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


class _FakeSessions:
    """One workspace directory per conversation key, like the real manager."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self.holders: dict[str, object] = {}

    async def acquire(self, key: str, *, holder: object = None) -> _FakeSession:
        path = self._root / key
        path.mkdir(parents=True, exist_ok=True)
        if holder is not None:
            self.holders[key] = holder
        return _FakeSession(path)


class _FakeProjects:
    def __init__(self, roots: dict[str, Path]) -> None:
        self._roots = roots

    async def get(self, owner_id: str, project_id: str):
        class _View:
            root_path = str(self._roots[project_id])
            base_ref = "main"

        return _View()


async def _git(cwd: Path, *args: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=str(cwd),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.communicate()


async def _repo(root: Path) -> Path:
    root.mkdir(parents=True)
    (root / "hello.txt").write_text("original\n")
    await _git(root, "git", "init", "-b", "main")
    await _git(root, "git", "add", "-A")
    await _git(root, "git", "-c", "user.name=T", "-c", "user.email=t@e", "commit", "-m", "first")
    return root


def _caps(tmp_path: Path, roots: dict[str, Path] | None = None) -> ServiceContainer:
    caps = ServiceContainer()
    caps.add(_FakeSessions(tmp_path / "sandbox"), as_type=SandboxSessionManager)
    if roots is not None:
        caps.add(_FakeProjects(roots), as_type=ProjectStore)
        caps.add(WorktreeManager(tmp_path / "worktrees"), as_type=WorktreeManager)
    return caps


def _ctx(caps: ServiceContainer, **deps) -> RunContext[RunDeps]:
    run = Run(id=deps.pop("run_id", "run-1"), kind="chat", owner_id=OWNER, stream=RunStream())
    return RunContext(
        deps=RunDeps(run=run, owner_id=OWNER, caps=caps, **deps),
        model=TestModel(),
        usage=RunUsage(),
    )


# --- normal mode: unchanged, and the /work translation is the resolver's --------------


class TestNormalMode:
    async def test_resolves_the_conversations_own_sandbox_workspace(self, tmp_path):
        ctx = _ctx(_caps(tmp_path), conversation_id="conv-a")
        workspace = await run_workspace(ctx)
        assert workspace is not None
        assert workspace.kind == "sandbox"
        assert workspace.root == tmp_path / "sandbox" / "conv-a"

    async def test_two_conversations_get_different_roots(self, tmp_path):
        caps = _caps(tmp_path)
        a = await run_workspace(_ctx(caps, conversation_id="conv-a", run_id="r1"))
        b = await run_workspace(_ctx(caps, conversation_id="conv-b", run_id="r2"))
        assert a is not None and b is not None
        # Rooting, not isolation: named directories, not merely distinct objects.
        assert a.root == tmp_path / "sandbox" / "conv-a"
        assert b.root == tmp_path / "sandbox" / "conv-b"

    async def test_the_model_is_told_the_mount_path_not_the_host_path(self, tmp_path):
        ctx = _ctx(_caps(tmp_path), conversation_id="conv-a")
        workspace = await run_workspace(ctx)
        assert workspace is not None
        # The host path means nothing on the other side of the bind mount.
        assert workspace.display("attachments/x.pdf") == f"{SANDBOX_MOUNT}/attachments/x.pdf"
        assert workspace.stage_prefix == ""

    async def test_no_sandbox_means_no_workspace(self, tmp_path):
        ctx = _ctx(ServiceContainer(), conversation_id="conv-a")
        assert await run_workspace(ctx) is None

    async def test_it_is_resolved_once_per_run(self, tmp_path):
        ctx = _ctx(_caps(tmp_path), conversation_id="conv-a")
        first = await run_workspace(ctx)
        second = await run_workspace(ctx)
        # A code turn's first resolution runs `git worktree add`; a turn makes many
        # file-tool calls, and it must not run once per call.
        assert first is second

    async def test_the_run_claims_the_container_it_is_about_to_work_in(self, tmp_path):
        # Without the claim the only "in use" signal is the exec lock, held for one call
        # out of the dozens a turn makes — and the live-session cap would be free to seal
        # the workspace away in a gap between two of them, taking `node_modules`, `.venv`
        # and `.git` with it (the seal drops those by design).
        caps = _caps(tmp_path)
        ctx = _ctx(caps, conversation_id="conv-a")
        await run_workspace(ctx)
        sessions = caps.get_optional(SandboxSessionManager)
        assert sessions is not None
        assert sessions.holders["conv-a"] is ctx.deps.run


# --- code mode: the worktree, and the one-workspace invariant ------------------------


class TestCodeMode:
    async def _ctx(self, tmp_path, *, conversation_id="conv-a", run_id="run-1"):
        root = await _repo(tmp_path / "project")
        caps = _caps(tmp_path, {"proj-1": root})
        return root, _ctx(
            caps,
            conversation_id=conversation_id,
            run_id=run_id,
            project_id="proj-1",
            mode="code",
        )

    async def test_resolves_the_projects_worktree_not_the_operators_tree(self, tmp_path):
        root, ctx = await self._ctx(tmp_path)
        workspace = await run_workspace(ctx)
        assert workspace is not None
        assert workspace.kind == "worktree"
        assert workspace.branch == "ody/conv-a"
        # The assertion the whole design exists for: never the operator's own checkout.
        assert workspace.root != root
        assert (workspace.root / "hello.txt").read_text() == "original\n"

    async def test_the_model_is_told_a_real_host_path(self, tmp_path):
        _root, ctx = await self._ctx(tmp_path)
        workspace = await run_workspace(ctx)
        assert workspace is not None
        # No `/work` here: the shell runs on the host, and a container path would name
        # a file it cannot open.
        shown = workspace.display("src/main.py")
        assert shown == str(workspace.root / "src/main.py")
        assert not shown.startswith(SANDBOX_MOUNT)

    async def test_staged_files_land_inside_the_worktree_and_out_of_the_diff(self, tmp_path):
        _root, ctx = await self._ctx(tmp_path)
        workspace = await run_workspace(ctx)
        assert workspace is not None
        # Inside, or the file tools cannot reach what was staged...
        assert workspace.stage_prefix == f"{WORKTREE_SCRATCH}/"
        workspace.files.write_file(f"{workspace.stage_prefix}attachments/a.txt", b"hi")
        assert (workspace.root / WORKTREE_SCRATCH / "attachments" / "a.txt").is_file()
        # ...and ignored, or the operator's review fills up with their own attachments.
        code, out = await _status(workspace.root)
        assert code == 0
        assert WORKTREE_SCRATCH not in out

    async def test_code_without_a_project_has_no_workspace_rather_than_a_sandbox(self, tmp_path):
        # Falling back to the sandbox would be the worst answer: the agent would edit
        # files in a container while its shell tools are refused, and nothing would say
        # why. `project_id` is required at thread creation precisely so this cannot
        # happen; if it does, it degrades visibly.
        caps = _caps(tmp_path, {})
        assert await run_workspace(_ctx(caps, conversation_id="c", mode="code")) is None
        # ...and likewise when the project id names nothing.
        ctx = _ctx(caps, conversation_id="c", mode="code", project_id="gone", run_id="r2")
        assert await run_workspace(ctx) is None


async def _status(cwd: Path) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        "git",
        "status",
        "--porcelain",
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    return proc.returncode or 0, out.decode()


# --- the shell refuses to run outside the mode it belongs to -------------------------


class TestShellIsCodingOnly:
    async def test_a_chat_run_is_refused_even_if_the_tool_is_reachable(self, tmp_path):
        # `mode_disabled_tools` normally hides these from a chat run. That is a filter,
        # and a filter is the wrong last line of defence between an unfenced host command
        # and a chat thread — so the toolset checks too. Calling it directly is exactly
        # the scenario a filter regression would produce.
        ctx = _ctx(_caps(tmp_path), conversation_id="conv-a")
        result = await shell_toolset().call_tool(
            "run_command",
            {"command": "echo hi"},
            ctx,
            None,  # type: ignore[arg-type]
        )
        assert "only available in a code conversation" in str(result)


class TestShellRecoverableFailures:
    async def test_a_command_the_os_wont_spawn_is_a_retry_not_a_dead_run(self, tmp_path):
        """The harness returns what the model can act on — a denied command, a working
        directory that vanished, a command the OS refuses to spawn — as `ModelRetry`, so
        the turn continues and the agent tries something else. Only failures it could do
        nothing about still abort.

        Pinned because it is behaviour we *inherit*: it arrived in a harness release
        rather than in code of ours, so nothing else here would notice it going away.
        """
        root = await _repo(tmp_path / "project")
        caps = _caps(tmp_path, {"proj-1": root})
        ctx = _ctx(caps, conversation_id="conv-a", project_id="proj-1", mode="code")
        toolset = shell_toolset()
        tools = await toolset.get_tools(ctx)

        async def run(command: str):
            return await toolset.call_tool(
                "run_command",
                {"command": command},
                ctx,
                tools["run_command"],
            )

        # Approval is the gate on the *first* command; `tool_call_approved` is what the
        # engine sets on the re-invocation, so drive the post-approval call directly.
        ctx.tool_call_approved = True

        # A destructive command the harness denies by name.
        with pytest.raises(ModelRetry):
            await run("rm -rf /")

        # A command holding a NUL byte, which the OS cannot spawn at all.
        with pytest.raises(ModelRetry):
            await run("echo \x00hi")

        # And the turn is still usable afterwards — a retry left nothing broken behind it.
        assert "ok" in str(await run("echo ok"))


class TestShellDeclaresAndEnforcesItsReach:
    """The model says how far a command needs to go; the tool holds it to that.

    The enforcement is here rather than at the permission gate on purpose: a declaration
    is a statement about the command, so it costs nothing to hold a command to its own
    statement at *every* level — including one the operator approved by hand, which never
    passed a gate at all.
    """

    async def _run(self, tmp_path, monkeypatch, command: str, **args):
        root = await _repo(tmp_path / "project")
        caps = _caps(tmp_path, {"proj-1": root})
        ctx = _ctx(caps, conversation_id="conv-a", project_id="proj-1", mode="code")
        ctx.tool_call_approved = True
        toolset = shell_toolset()
        tools = await toolset.get_tools(ctx)
        wrapped: list[str] = []

        async def recording(command, profile, *, cwd=None):
            # Returned unchanged so the command still runs; what is under test is whether
            # the fence was asked for it at all, and with which profile.
            wrapped.append(command)
            self.profile = profile
            self.cwd = cwd
            return command

        monkeypatch.setattr(shell_module.fence, "wrap", recording)
        result = await toolset.call_tool(
            "run_command", {"command": command, **args}, ctx, tools["run_command"]
        )
        return wrapped, str(result)

    def _fenced_host(self, monkeypatch) -> None:
        async def available(settings):
            return HostConfinement(True)

        monkeypatch.setattr(shell_module.fence, "fence_available", available)

    async def test_the_declaration_is_offered_to_the_model_with_the_workspace_default(
        self, tmp_path
    ):
        caps = _caps(tmp_path, {"proj-1": tmp_path})
        ctx = _ctx(caps, conversation_id="conv-a", project_id="proj-1", mode="code")
        tool = (await shell_toolset().get_tools(ctx))["run_command"]
        schema = tool.tool_def.parameters_json_schema
        reach = schema["properties"]["reach"]
        assert "reach" not in schema.get("required", [])
        assert reach.get("default") == "workspace"
        # The description explains the fence and never the permission level: one string
        # ships at all four, so a promise about an approval outcome is wrong at three.
        assert "fence" in str(reach.get("description", "")).lower()
        assert "approv" not in str(reach.get("description", "")).lower()

    async def test_a_contained_command_runs_inside_the_fence(self, tmp_path, monkeypatch):
        self._fenced_host(monkeypatch)
        wrapped, output = await self._run(tmp_path, monkeypatch, "echo ok")
        assert wrapped == ["echo ok"]
        assert "ok" in output

    async def test_a_host_declaration_is_run_as_the_approver_read_it(
        self, tmp_path, monkeypatch
    ):
        # `host` is the declaration that asks for no fence, and it has already been
        # approved *as that*: wrapping it in one anyway would break the act somebody said
        # yes to, which is the opposite of enforcing the declaration.
        self._fenced_host(monkeypatch)
        wrapped, output = await self._run(tmp_path, monkeypatch, "echo ok", reach="host")
        assert wrapped == []
        assert "ok" in output

    async def test_a_command_the_structure_contradicts_is_not_fenced_either(
        self, tmp_path, monkeypatch
    ):
        # It escalated to a reviewer or to the operator, who ruled on the command as
        # written; there is no tier here to build a profile from.
        self._fenced_host(monkeypatch)
        wrapped, _output = await self._run(tmp_path, monkeypatch, "echo ok > /etc/nope")
        assert wrapped == []

    @pytest.mark.parametrize(
        "command",
        [
            "echo $(printf ok)",  # a nested command, unreadable rather than escaping
            "sh -c 'echo ok'",  # an argument that could itself be a command line
            "echo 'two words'",  # ...and the same shape spelled innocently
        ],
    )
    async def test_a_command_the_judge_could_not_read_is_still_fenced(
        self, tmp_path, monkeypatch, command
    ):
        # The lever this closes: the judge declines these for being *unreadable*, not for
        # reaching anywhere, and a fence keyed off the judgement alone would have let any
        # command escape it by being written so nothing could read it — the model choosing
        # whether the OS boundary applies. What it declared is still a statement about the
        # command, and a reviewer who allowed it was never asked about the fence.
        self._fenced_host(monkeypatch)
        wrapped, _output = await self._run(tmp_path, monkeypatch, command)
        assert wrapped == [command]

    async def test_the_directory_capture_carries_the_root_it_may_not_leave(
        self, tmp_path, monkeypatch
    ):
        # What the outer shell ends in is what the session persists, so the capture is
        # gated on the worktree root — otherwise a `cd` out of it would leave every later
        # relative path judged against a directory the command is no longer in.
        self._fenced_host(monkeypatch)
        await self._run(tmp_path, monkeypatch, "echo ok")
        assert self.cwd is not None
        # The same root the profile's write allow is built from — one directory, two uses,
        # and a capture gated on a different one would gate on nothing.
        assert str(self.cwd.root) in self.profile.filesystem.allow_write

    async def test_without_a_primitive_the_command_runs_unfenced(self, tmp_path, monkeypatch):
        # The suite runs with confinement off, so this is the default path: nothing clears
        # structurally, and nothing is wrapped in a fence that does not exist.
        wrapped, output = await self._run(tmp_path, monkeypatch, "echo ok")
        assert wrapped == []
        assert "ok" in output


@pytest.mark.fence
class TestAFencedCommandStillBehavesLikeAShell:
    """The whole glue, once: the tool's fence wrap, the harness's own checks, a real spawn.

    Everything above stops at the wrapper's string. What is not provable there is the part
    with two authors — the harness appends its own `pwd > …` to whatever it is handed, and
    that suffix lands *outside* the sandboxed shell, where it would record the directory
    the tool started in and quietly undo every `cd` the model wrote. So this runs commands
    for real and asks the two questions a broken shim answers wrongly while every string
    assertion still passes: does a `cd` survive to the next call, and does a failing
    command still come back as failed.
    """

    async def _session(self, tmp_path: Path, monkeypatch):
        settings = Settings(data_dir=tmp_path / "data", host_command_sandbox_enabled=True)
        confinement = await host_module._configure(settings)
        if not confinement.active:
            pytest.skip(f"no host sandbox primitive here: {confinement.reason}")
        # The real `fence_available` reads a process-global that the suite deliberately
        # leaves unresolved; the settings are the tool's own lookup, and both have to say
        # the same thing or the command would be judged fenced and run bare.
        monkeypatch.setattr(host_module, "_resolved", confinement)
        monkeypatch.setattr(shell_module, "get_settings", lambda: settings)
        root = await _repo(tmp_path / "project")
        caps = _caps(tmp_path, {"proj-1": root})
        ctx = _ctx(caps, conversation_id="conv-a", project_id="proj-1", mode="code")
        ctx.tool_call_approved = True
        toolset = shell_toolset()
        tools = await toolset.get_tools(ctx)

        async def run(command: str) -> str:
            return str(
                await toolset.call_tool(
                    "run_command", {"command": command}, ctx, tools["run_command"]
                )
            )

        return run

    async def test_a_cd_survives_to_the_next_fenced_command(self, tmp_path, monkeypatch):
        run = await self._session(tmp_path, monkeypatch)
        assert "Operation not permitted" not in await run("mkdir -p sub && cd sub")
        assert "/sub" in await run("pwd")

    async def test_a_denial_reaches_the_model_as_the_fence_and_not_as_a_broken_tool(
        self, tmp_path, monkeypatch
    ):
        # Also the proof that the two tests either side of this one ran fenced at all: the
        # repository's `config` is the one path denied *inside* an allowed one, so a
        # failure here cannot come from anything but the profile. And the note is what
        # turns `Operation not permitted` into something the model can act on — without it
        # its next move on an apparently broken tool is to try again.
        run = await self._session(tmp_path, monkeypatch)
        # Spelled with a bare word rather than a path: `/tmp/x` would leave the worktree,
        # which the structural stage refuses outright, and the command would then run
        # *unfenced* as the thing a reviewer or the operator ruled on.
        output = await run("git config core.fsmonitor sneaky")
        assert "Operation not permitted" in output
        assert "[fence]" in output and "declare the reach" in output

    async def test_a_failing_command_still_comes_back_failed(self, tmp_path, monkeypatch):
        # The wrapper *sets* the inner exit code rather than exiting on it, so that the
        # harness's own suffix can still run. Getting that backwards makes every fenced
        # command look successful.
        run = await self._session(tmp_path, monkeypatch)
        assert "1" in await run("false")
        assert "ok" in await run("echo ok")


# --- the host-side staging adapter ---------------------------------------------------


class TestHostFiles:
    def test_a_write_outside_the_root_is_refused(self, tmp_path):
        # A staged filename is operator content; containment is the sandbox's own check,
        # reused rather than re-derived.
        files = HostFiles(tmp_path)
        with pytest.raises(SandboxError):
            files.write_file("../escaped.txt", b"x")

    def test_round_trips_within_the_root(self, tmp_path):
        files = HostFiles(tmp_path)
        files.write_file("nested/a.txt", b"hi")
        assert files.read_file("nested/a.txt") == b"hi"


# --- the resolver's own contract -----------------------------------------------------


class TestResolveWorkspace:
    async def test_no_handles_at_all_is_no_workspace(self):
        assert (
            await resolve_workspace(
                mode="normal",
                project_id=None,
                conversation_id="c",
                sandbox_key="c",
                owner_id=OWNER,
                sessions=None,
                projects=None,
                worktrees=None,
            )
            is None
        )

    def test_display_never_doubles_a_separator(self, tmp_path):
        workspace = RunWorkspace(root=tmp_path, kind="sandbox", files=HostFiles(tmp_path))
        assert workspace.display("/attachments/a") == f"{SANDBOX_MOUNT}/attachments/a"
