"""The code-mode shell, and the fence it will not run without.

Two things are pinned here and they fail in opposite directions. The **shape** is the
harness `Shell`'s — a `cd` that persists, a denylisted command that comes back as a retry,
a background process that can be checked and stopped — because the model was trained on it
and a first-party reimplementation is exactly the kind of thing that drifts quietly. The
**fence** is ours: every command goes through a confiner, with this conversation's egress
set and its worktree as the writable root, and when there is no confiner to go through the
tools refuse in words instead of running anyway.

The confiner is faked at the seam rather than exercised for real. Driving seatbelt from a
test would pin the platform's behaviour, not this code's, and only on the machines that
have it; what is worth asserting is that the arguments handed to the fence are the right
ones, which a recording stub says far more precisely.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.exceptions import ApprovalRequired
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from core.config import get_settings
from core.container import ServiceContainer
from runs import Run, RunStream
from services.egress import EgressPolicy
from services.projects import ProjectStore, WorktreeManager
from services.sandbox.host import HostConfinement
from tools.deps import RunDeps
from tools.shell import shell_toolset
from tools.workspace import run_workspace

from .conftest import egress_policy, unfenced

OWNER = "operator"


class _Projects:
    def __init__(self, root: Path) -> None:
        self._root = root

    async def get(self, owner_id: str, project_id: str):
        class _View:
            root_path = str(self._root)
            base_ref = "main"

        return _View()


class _Recorder:
    """A confiner that runs the command untouched and remembers how it was fenced."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def __call__(self, command: str, *, allowed_domains, allow_write, deny_read) -> str:
        self.calls.append(
            {
                "allowed_domains": set(allowed_domains),
                "allow_write": tuple(allow_write),
                "deny_read": tuple(deny_read),
            }
        )
        return command


def _resolved(paths) -> set[str]:
    """The write list with symlinks settled — on macOS a temp path reaches the fence as
    `/var/...` or `/private/var/...` depending on who derived it."""
    return {str(Path(path).resolve()) for path in paths}


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


def _ctx(tmp_path: Path, root: Path, *, egress=None) -> RunContext[RunDeps]:
    caps = ServiceContainer()
    caps.add(_Projects(root), as_type=ProjectStore)
    caps.add(WorktreeManager(tmp_path / "worktrees"), as_type=WorktreeManager)
    if egress is not None:
        caps.add(egress, as_type=EgressPolicy)
    run = Run(id="run-1", kind="chat", owner_id=OWNER, stream=RunStream())
    return RunContext(
        deps=RunDeps(
            run=run,
            owner_id=OWNER,
            caps=caps,
            conversation_id="conv-a",
            project_id="proj-1",
            mode="code",
        ),
        model=TestModel(),
        usage=RunUsage(),
    )


class _Shell:
    """The four tools, driven the way the engine drives them."""

    def __init__(self, toolset, ctx) -> None:
        self._toolset = toolset
        self.ctx = ctx
        self._tools: dict | None = None

    async def call(self, name: str, **args) -> str:
        if self._tools is None:
            self._tools = await self._toolset.get_tools(self.ctx)
        return str(await self._toolset.call_tool(name, args, self.ctx, self._tools[name]))


async def _shell(tmp_path: Path, *, confiner=unfenced, egress=None, approved=True) -> _Shell:
    root = await _repo(tmp_path / "project")
    ctx = _ctx(tmp_path, root, egress=egress)
    # Approval gates the *first* command of a conversation; `tool_call_approved` is what
    # the engine sets on the re-invocation, so drive the post-approval call directly.
    ctx.tool_call_approved = approved
    return _Shell(shell_toolset(confiner=confiner), ctx)


# --- the shape the model already knows ------------------------------------------------


async def test_a_cd_moves_where_the_next_command_runs(tmp_path):
    # The judge reads a relative path against wherever the last command left the shell
    # (`services/permissions/judge.py`), and `cd` is deliberately not allowlisted — so if
    # the working directory stopped persisting, the judge would be reasoning about the
    # wrong directory rather than failing loudly.
    shell = await _shell(tmp_path)
    await shell.call("run_command", command="mkdir -p sub")
    before = await shell.call("run_command", command="pwd")
    await shell.call("run_command", command="cd sub")
    after = await shell.call("run_command", command="pwd")
    assert after.strip().endswith("/sub")
    assert after != before


async def test_a_failed_cd_leaves_the_directory_where_it_was(tmp_path):
    shell = await _shell(tmp_path)
    before = await shell.call("run_command", command="pwd")
    result = await shell.call("run_command", command="cd nowhere-at-all")
    assert "[exit code:" in result
    assert await shell.call("run_command", command="pwd") == before


async def test_a_destructive_command_comes_back_as_a_retry(tmp_path):
    shell = await _shell(tmp_path)
    with pytest.raises(ModelRetry):
        await shell.call("run_command", command="rm -rf /")
    # ...and the turn is still usable: a refusal spawned nothing to clean up.
    assert "ok" in await shell.call("run_command", command="echo ok")


async def test_a_background_command_is_started_checked_and_stopped(tmp_path):
    shell = await _shell(tmp_path)
    started = await shell.call("start_command", command="echo up; sleep 30")
    command_id = started.rsplit("ID: ", 1)[1].strip()

    for _ in range(50):  # the process has to reach its first write
        checked = await shell.call("check_command", command_id=command_id)
        if "up" in checked:
            break
        await asyncio.sleep(0.05)
    assert "up" in checked and "[status: running]" in checked

    stopped = await shell.call("stop_command", command_id=command_id)
    assert "[stopped]" in stopped
    # The id is spent: a second stop finds nothing rather than killing a reused pid.
    assert "unknown command ID" in await shell.call("stop_command", command_id=command_id)


async def test_a_cancelled_command_takes_its_process_tree_with_it(tmp_path):
    # The operator presses Stop, or the run hits its bound. Unwinding without reaping
    # would leave a build or a server running on the operator's real machine with no run
    # left to stop it — the same promise the hatch keeps on its own cancellation path.
    shell = await _shell(tmp_path)
    await shell.call("run_command", command="echo warm")  # worktree and toolset settled
    started = tmp_path / "started"
    orphan = tmp_path / "orphan-ran"
    task = asyncio.create_task(
        shell.call(
            "run_command", command=f"( sleep 2; touch {orphan} ) & touch {started}; wait"
        )
    )
    for _ in range(100):
        if started.exists():
            break
        await asyncio.sleep(0.05)
    assert started.exists()  # the tree is up, so cancelling has something to reap

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(2.5)  # past when a survivor would have written
    assert not orphan.exists()


async def test_an_unknown_background_id_is_answered_not_raised(tmp_path):
    shell = await _shell(tmp_path)
    assert "unknown command ID" in await shell.call("check_command", command_id="nope")


async def test_the_operators_model_keys_are_not_in_the_environment(tmp_path, monkeypatch):
    # Not a boundary — same-user processes can reach the parent's environment through the
    # OS — but the keys must not be sitting in the one place a command reads by accident.
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-appear")
    monkeypatch.setenv("HARMLESS_VAR", "kept")
    shell = await _shell(tmp_path)
    printed = await shell.call(
        "run_command", command="echo ${OPENAI_API_KEY:-absent} $HARMLESS_VAR"
    )
    assert "sk-should-not-appear" not in printed
    assert "absent" in printed and "kept" in printed


# --- the fence ------------------------------------------------------------------------


async def test_without_a_fence_the_tools_refuse_and_say_what_is_missing(tmp_path, monkeypatch):
    # The inverse of the host hatch, on purpose: nobody consented to an unfenced agent
    # shell, and a code conversation is a long stretch of commands nobody reads one by one.
    async def no_primitive(_settings):
        return HostConfinement(False, "ripgrep (`rg`) is not installed")

    monkeypatch.setattr("tools.shell.resolve_confinement", no_primitive)
    shell = await _shell(tmp_path, confiner=None)
    refusal = await shell.call("run_command", command="echo should-not-run")
    assert "cannot be confined" in refusal
    assert "ripgrep" in refusal  # the missing primitive, named
    assert "should-not-run" not in refusal  # and nothing ran


async def test_the_fence_is_asked_for_this_conversations_egress_and_its_worktree(tmp_path):
    policy = egress_policy(tmp_path, ("pypi.org",))
    await policy.allow("conv-a", ["files.example.com"])
    recorder = _Recorder()
    shell = await _shell(tmp_path, confiner=recorder, egress=policy)
    await shell.call("run_command", command="echo fenced")

    [call] = recorder.calls
    # Everything this conversation may reach, which on the host decides whether the
    # command gets a route out at all — the proxy filters against the installation's list.
    assert call["allowed_domains"] == {"pypi.org", "files.example.com"}
    # Writes land in the run's own worktree, which is not the operator's checkout...
    workspace = await run_workspace(shell.ctx)
    assert workspace is not None and workspace.root != tmp_path / "project"
    assert str(workspace.root) in call["allow_write"]
    # ...and so does git: a linked worktree keeps its index, refs and objects in the
    # project's repository, so without them not even a `git status` that refreshes the
    # index would work on the throwaway branch the worktree exists for.
    git = (tmp_path / "project" / ".git").resolve()
    assert str(git / "objects") in _resolved(call["allow_write"])
    # ...and the data directory — the vault, the sealed workspaces, the database — is
    # unreadable whatever else is.
    assert str(Path(get_settings().data_dir).resolve()) in call["deny_read"]


async def test_the_project_repository_is_writable_where_git_stores_and_nowhere_else(tmp_path):
    # `.git/hooks` is code the operator's own git runs later, outside every fence, and
    # `.git/config` can name a command it runs for them. Neither is storage, and handing
    # either over would change what happens on the operator's machine without the merge
    # they approve — so the parts git writes are named one by one rather than the
    # directory holding them. The ref store is named more precisely still: only the
    # namespace coding branches live in, because git is not the enforcer here and a
    # writable `refs/heads` is `git update-ref refs/heads/main <sha>` — the operator's own
    # branch moved without the merge that is supposed to move it.
    recorder = _Recorder()
    shell = await _shell(tmp_path, confiner=recorder)
    await shell.call("run_command", command="echo fenced")

    [call] = recorder.calls
    git = (tmp_path / "project" / ".git").resolve()
    workspace = await run_workspace(shell.ctx)
    assert workspace is not None
    gitdir = Path((workspace.root / ".git").read_text().partition("gitdir:")[2].strip())
    granted = {path for path in _resolved(call["allow_write"]) if path.startswith(str(git))}
    assert granted == {
        str(gitdir.resolve()),  # this worktree's own index and HEAD, not its siblings'
        str(git / "objects"),
        str(git / "refs" / "heads" / "ody"),
        str(git / "logs" / "refs" / "heads" / "ody"),
    }
    # Nothing granted contains a branch of the operator's.
    operator_branch = git / "refs" / "heads" / "main"
    assert not any(operator_branch.is_relative_to(Path(path)) for path in granted)


async def test_every_command_goes_through_the_fence_including_background_ones(tmp_path):
    recorder = _Recorder()
    shell = await _shell(tmp_path, confiner=recorder)
    await shell.call("run_command", command="echo one")
    started = await shell.call("start_command", command="sleep 5")
    await shell.call("stop_command", command_id=started.rsplit("ID: ", 1)[1].strip())
    # `check` and `stop` act on a process already fenced into existence; the two that
    # start something are the two that must be wrapped.
    assert len(recorder.calls) == 2


async def test_the_first_command_of_a_conversation_asks_the_operator(tmp_path):
    shell = await _shell(tmp_path, approved=False)
    with pytest.raises(ApprovalRequired):
        await shell.call("run_command", command="echo hi")
    # Checking on something already approved into existence does not re-ask.
    assert "unknown command ID" in await shell.call("check_command", command_id="whatever")
