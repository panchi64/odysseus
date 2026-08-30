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

from core.container import ServiceContainer
from runs import Run, RunStream
from services.projects import ProjectStore, WorktreeManager
from services.sandbox import SandboxError, SandboxSessionManager
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

    async def acquire(self, key: str) -> _FakeSession:
        path = self._root / key
        path.mkdir(parents=True, exist_ok=True)
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


# --- chat mode: unchanged, and the /work translation is the resolver's ----------------


class TestChatMode:
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
        # A coding turn's first resolution runs `git worktree add`; a turn makes many
        # file-tool calls, and it must not run once per call.
        assert first is second


# --- coding mode: the worktree, and the one-workspace invariant ----------------------


class TestCodingMode:
    async def _ctx(self, tmp_path, *, conversation_id="conv-a", run_id="run-1"):
        root = await _repo(tmp_path / "project")
        caps = _caps(tmp_path, {"proj-1": root})
        return root, _ctx(
            caps,
            conversation_id=conversation_id,
            run_id=run_id,
            project_id="proj-1",
            mode="coding",
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

    async def test_coding_without_a_project_has_no_workspace_rather_than_a_sandbox(self, tmp_path):
        # Falling back to the sandbox would be the worst answer: the agent would edit
        # files in a container while its shell tools are refused, and nothing would say
        # why. `project_id` is required at thread creation precisely so this cannot
        # happen; if it does, it degrades visibly.
        caps = _caps(tmp_path, {})
        assert await run_workspace(_ctx(caps, conversation_id="c", mode="coding")) is None
        # ...and likewise when the project id names nothing.
        ctx = _ctx(caps, conversation_id="c", mode="coding", project_id="gone", run_id="r2")
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
        assert "only available in a coding conversation" in str(result)


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
        ctx = _ctx(caps, conversation_id="conv-a", project_id="proj-1", mode="coding")
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
                mode="chat",
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
