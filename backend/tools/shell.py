"""The `shell` category — running commands in a code conversation's worktree.

Four tools: `run_command` (blocking), `start_command` / `check_command` / `stop_command`
(background), so a dev server or a long test run is a process the agent checks on rather
than a turn that blocks for ten minutes. Rebound per run to the project's worktree, the
same way `files` is. The mechanics are in ``services/sandbox/shell_runner.py``; this file
is the contract the model sees.

**The fence is required here.** Every command is wrapped by the same OS-level confinement
an approved host command runs under — the credential paths and the data directory
unreadable, writes landing in the worktree and the build caches, egress off the machine
only to the installation's allowlist (loopback stays open, so a dev server and its tests
work; ``services/sandbox/host.py`` states what that leaves reachable). Unlike the host
hatch, which degrades and says so because the operator approved *that specific command*,
this refuses when the platform has no
primitive: nobody consented to an unfenced agent shell, and a code conversation is a long
stretch of commands nobody reads one by one.

What makes that fence affordable is everything around it — the throwaway branch the edits
land on, the merge the operator has to approve, one approval on the conversation's first
command, and code mode being chosen for a thread bound to a project they named. An
allowlist of programs was considered instead of that approval and rejected: an agent
writing code needs whatever build tool the project uses, so any allowlist honest enough to
be useful is long enough to be meaningless, and it would still be bypassable through an
allowed interpreter.

**Refused outright outside a worktree mode.** `mode_disabled_tools` already hides these
tools from every mode whose spec does not admit the `shell` category, but that is a
filter, and a filter is the wrong place for the only thing standing between a host command
and a sandbox thread. The check is here too.
"""

from __future__ import annotations

import os
import sys
import tempfile
from functools import partial
from pathlib import Path

from pydantic_ai import AbstractToolset, FunctionToolset, RunContext
from pydantic_ai.exceptions import ApprovalRequired

from core.config import Settings, get_settings
from services.egress import EgressPolicy
from services.modes import mode_spec
from services.projects import BRANCH_PREFIX
from services.sandbox.host import confine, denied_reads, resolve_confinement
from services.sandbox.shell_runner import Confiner, FencedShell
from services.workspace import RunWorkspace

from .deps import RunDeps
from .rebound import WorkspaceToolset

#: Long enough for a real build or test suite; short enough that a hung command doesn't
#: hold the turn open indefinitely. The agent can pass its own timeout per call, and any
#: genuinely long-running thing belongs in `start_command`.
_TIMEOUT_S = 300.0

#: Effectively no cap. This codebase has one context reduction — conversation compaction,
#: on measured pressure — and truncating a tool result is exactly what was torn out of
#: `code_execute`. A pathological command's output is caught by the run's own
#: context-overflow stop, which says so out loud rather than silently costing the model
#: the middle of what it just asked for.
_MAX_OUTPUT_CHARS = 2_000_000

#: The two tools that execute something new. `check_command` and `stop_command` act on a
#: process that was already approved into existence, so re-asking would be noise.
EXECUTING_TOOLS = frozenset({"run_command", "start_command"})

#: The same two, namespaced — the conditionally-gated names this category contributes to
#: the approval-scope vocabulary. **This declaration is what makes the gate usable.** The
#: raise below parks the run either way, but a name absent from `app.state.gated_tools`
#: never reaches `tools/catalog.approval_scopes`, so the operator could not grant it for
#: the conversation (nor pre-authorize it on a scheduled task) and would be asked again on
#: every single command — which would make the approval gate the nuisance an allowlist was
#: rejected for being.
GATED_TOOLS = frozenset(f"shell_{name}" for name in EXECUTING_TOOLS)

_WRONG_MODE = (
    "Shell commands are only available in a code conversation, which runs in a "
    "project's git worktree. This conversation runs in a container — use `code_execute` "
    "instead."
)

_NO_FENCE = (
    "Shell commands are unavailable: they cannot be confined on this machine ({reason}). "
    "Every command in a code conversation runs under OS-level confinement, and running "
    "one without it is not something this tool will do. Tell the operator what is "
    "missing; until it is fixed, work by reading and editing files rather than by "
    "running commands, and say plainly what you could not verify."
)


async def _fence_gap(confiner: Confiner | None) -> str:
    """Why commands would run unfenced, or "" when they will not.

    An injected confiner *is* the fence — the caller supplied one, and there is nothing to
    probe. Without one the platform's is resolved, which is also what configures it.
    """
    if confiner is not None:
        return ""
    resolved = await resolve_confinement(get_settings())
    return "" if resolved.active else resolved.reason


async def _guard(
    name: str,
    ctx: RunContext[RunDeps],
    workspace: RunWorkspace,
    *,
    confiner: Confiner | None,
) -> str | None:
    """Refuse outside a worktree mode or without a fence; otherwise pause for approval on
    the first command.

    Both refusals are plain strings rather than `ModelRetry`: neither is something the
    model can fix by rephrasing, and handing it a retry would only buy a loop.
    `tool_call_approved` is set on the re-invocation after an approval, so the raise below
    fires once and then lets the command run — and a conversation-scoped grant means the
    operator is asked once per thread, not once per command.
    """
    if mode_spec(ctx.deps.mode).workspace != "worktree" or workspace.kind != "worktree":
        return _WRONG_MODE
    gap = await _fence_gap(confiner)
    if gap:
        return _NO_FENCE.format(reason=gap)
    approved = ctx.tool_call_approved or ctx.deps.delegated_approved
    if name in EXECUTING_TOOLS and not approved:
        raise ApprovalRequired()
    return None


async def _domains(ctx: RunContext[RunDeps]) -> frozenset[str]:
    """Everything this conversation may reach. No policy means nothing is known to be
    allowed, and the command runs with no network at all — the fence is not the place to
    guess.

    What the host fence does with this is coarser than the set suggests: one proxy serves
    every confined process, so it filters against the installation-wide allowlist and this
    only decides whether the command gets a route out at all (see
    ``services/sandbox/host.confine``). A conversation's own grants widen the container
    fence, not this one.
    """
    policy = ctx.deps.caps.get_optional(EgressPolicy)
    if policy is None:
        return frozenset()
    return await policy.allowed_for(ctx.deps.workspace_key)


#: The corner of the ref store coding conversations own — every one of their branches is
#: namespaced under it (``services/projects/worktree.py``), and nothing of the operator's
#: is.
_BRANCHES = BRANCH_PREFIX.rstrip("/")

#: What a command in a worktree writes inside the project's *common* repository: the object
#: store, and the ref and reflog a commit moves — those two only under the branch namespace
#: above. `refs` and `logs` whole would be the operator's own ref store, and git is not the
#: enforcer here: `git update-ref refs/heads/main <sha>`, `git branch -f`, or a plain
#: redirect into the file would move the branch they have checked out, which is the merge
#: they approve happening without them. The rest of `.git` is left out because two of its
#: entries are exits rather than storage — `hooks/` is code the operator's own `git` runs
#: later, outside every fence, and `config` can name a command it runs for them
#: (`core.sshCommand`, aliases). Enumerating also fails in the safe direction as `.git`
#: grows entries nobody here has heard of yet.
_GIT_WRITES = ("objects", f"refs/heads/{_BRANCHES}", f"logs/refs/heads/{_BRANCHES}")


def _git_paths(root: Path) -> tuple[str, ...]:
    """Where this worktree's git writes outside ``root``, if anywhere.

    A coding workspace is a linked worktree, so its `.git` is a *pointer file* and the
    index, the refs and the object store live in the project's own repository — which is
    outside the worktree and therefore outside everything else on the write list. Without
    them `git add`, `git commit` and even a `git status` that has to refresh the index are
    denied, which is the one workflow the throwaway branch exists for. `git stash` is not
    on that list: `refs/stash` is shared with the operator's own checkout, so it stays out
    of reach along with every other ref they own.
    """
    pointer = root / ".git"
    try:
        # A directory (a plain clone rather than a worktree) raises here, and is already
        # covered by `root` itself.
        marker = pointer.read_text(encoding="utf-8").partition("gitdir:")[2].strip()
    except (OSError, ValueError):
        return ()
    if not marker:
        return ()
    gitdir = Path(marker) if Path(marker).is_absolute() else root / marker
    # `<project>/.git/worktrees/<name>` — this worktree's own index and HEAD live there,
    # and only there; the objects and refs land in the repository that owns that directory.
    # Its siblings are other conversations' worktrees, so the grant is this one by name.
    parent = gitdir.parent
    if parent.name != "worktrees":
        return tuple(str(gitdir / name) for name in _GIT_WRITES)
    return (str(gitdir), *(str(parent.parent / name) for name in _GIT_WRITES))


def _writable(root: Path) -> tuple[str, ...]:
    """Where a command may write: its own worktree, the parts of the repository behind it
    that git has to touch, and the caches a build fills.

    Writes are deny-by-default under the confinement, so this is not a hardening knob — it
    is what keeps `npm install` and `cargo build` from failing in a way that reads as the
    tool being broken. `gettempdir()` rather than a literal `/tmp` because macOS gives each
    user a private `TMPDIR` under `/var/folders`.
    """
    home = Path.home()
    # uv keeps its cache outside `~/.cache` on macOS, so the platform's own location is
    # asked for rather than assumed; an operator's `UV_CACHE_DIR` wins over both.
    uv_cache = os.environ.get("UV_CACHE_DIR") or str(
        home / ("Library/Caches/uv" if sys.platform == "darwin" else ".cache/uv")
    )
    return (
        str(root),
        *_git_paths(root),
        tempfile.gettempdir(),
        str(home / ".cache"),
        str(home / ".npm"),
        str(home / ".cargo"),
        uv_cache,
    )


def _tools_for(shell: FencedShell) -> FunctionToolset[RunDeps]:
    """The four tools, over one bound shell."""
    toolset: FunctionToolset[RunDeps] = FunctionToolset()

    @toolset.tool
    async def run_command(
        ctx: RunContext[RunDeps], command: str, timeout_seconds: float | None = None
    ) -> str:
        """Execute a shell command and return its output.

        Args:
            command: The shell command to run.
            timeout_seconds: Maximum seconds to wait (default: 300).

        Returns:
            Labeled stdout/stderr output with exit code on non-zero exit.
        """
        return await shell.run(
            command, domains=await _domains(ctx), timeout_seconds=timeout_seconds
        )

    @toolset.tool
    async def start_command(ctx: RunContext[RunDeps], command: str) -> str:
        """Start a long-running command in the background (e.g. a server or watcher).

        Callers MUST call `stop_command(command_id)` when done to terminate the
        process and clean up temporary output files.

        Args:
            command: The shell command to run in the background.

        Returns:
            A message containing the unique command ID for later check/stop calls.
        """
        return await shell.start(command, domains=await _domains(ctx))

    @toolset.tool
    async def check_command(ctx: RunContext[RunDeps], command_id: str) -> str:
        """Check the status and recent output of a background command.

        Args:
            command_id: The ID returned by start_command.

        Returns:
            Status and recent output of the background command.
        """
        return await shell.check(command_id)

    @toolset.tool
    async def stop_command(ctx: RunContext[RunDeps], command_id: str) -> str:
        """Stop a background command and return its final output.

        Args:
            command_id: The ID returned by start_command.

        Returns:
            Final output and exit status of the stopped command.
        """
        return await shell.stop(command_id)

    return toolset


def _toolset_for(
    root: Path,
    *,
    confiner: Confiner,
    settings: Settings,
    shells: list[FencedShell] | None = None,
) -> AbstractToolset[RunDeps]:
    shell = FencedShell(
        root,
        confiner=confiner,
        # The same paths the host hatch cannot read: one derivation, so a path added
        # for one fence cannot be left out of the other.
        deny_read=denied_reads(settings),
        allow_write=_writable(root),
        default_timeout=_TIMEOUT_S,
        max_output_chars=_MAX_OUTPUT_CHARS,
    )
    if shells is not None:
        shells.append(shell)
    return _tools_for(shell)


def shell_toolset(
    *, confiner: Confiner | None = None, shells: list[FencedShell] | None = None
) -> AbstractToolset[RunDeps]:
    """The `shell` category, built once per turn and rebound per run's worktree.

    ``confiner`` replaces the platform's fence, and is how a test drives these tools
    without running seatbelt over its own machine. Passing one asserts that commands are
    fenced, so it is never a way to switch the fence off.

    ``shells`` collects every shell this toolset binds, for the one caller that owns their
    lifetime: a conversation's shell outlives its turns on purpose and is stopped through
    `stop_command`, while a delegated run's workspace is taken away when it ends, so what
    it left running has to be reaped with it (``tools/worker.py``).
    """
    settings = get_settings()
    build = partial(_toolset_for, confiner=confiner or confine, settings=settings, shells=shells)
    return WorkspaceToolset(
        "shell",
        build(Path("/nonexistent-template-root")),
        build,
        guard=partial(_guard, confiner=confiner),
    )
