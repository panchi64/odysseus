"""The `shell` category — running commands in a code conversation's worktree.

`pydantic_ai_harness`'s `Shell`: `run_command` (blocking), `start_command` /
`check_command` / `stop_command` (background), so a dev server or a long test run is a
process the agent checks on rather than a turn that blocks for ten minutes. Rebound per
run to the project's worktree, the same way `files` is.

**The two executing tools are ours, and they take a third argument: `reach`.** The model
says how far a command needs to go — the worktree, the network, or the operator's whole
machine — and this file *enforces* that declaration by wrapping the command in a matching
OS fence (``services/sandbox/fence.py``) before the harness ever spawns it. A `workspace`
command that writes outside the worktree, or that reaches the network at all, fails inside
the fence with a note it can act on instead of quietly succeeding.

**Reads are the one half of a declaration the fence cannot hold**, and it belongs here
rather than only where the profile is built: the runtime offers a read denylist and no read
allowlist, so what bounds a read is the stage that ruled on the command
(``services/permissions/judge.py``, ``shell_ast.py``) — never this wrapper. What the fence
makes binding is the *write* and *egress* halves.

**The fence is applied at every permission level, and to every command — cleared or not.**
A declaration is a statement about the command, and it costs nothing to hold a command to
its own statement whether the operator approved it by hand or a review cleared it. The
permission layer's own use of the same declaration (``services/permissions/judge.py``) is
what decides *who approves*; this decides what the boundary is. In particular a command the
deterministic stage *declined* is still fenced to what it declared: its refusals are about
readability, and keying the fence off them would let a command escape by being written so
nothing could read it. The two exceptions are the approver's own: a `host` declaration, and
a declaration the command's syntax contradicts — both of which were approved as read.

**What still holds when the fence cannot be built.** Not every host has the primitive
(macOS seatbelt, Linux bubblewrap, plus `ripgrep` on PATH), and where it is missing the
deterministic stage clears nothing — every command goes to the model reviewer or to the
operator. Underneath that, unchanged:

- the **worktree and its branch** — the agent's edits land on a throwaway branch, and the
  operator's own checkout is written only by a merge they approve;
- **approval on the first command** of a conversation, grantable for the thread, so an
  agent cannot start executing on the host without the operator having said yes once;
- **`denied_env_patterns`**, which keeps the operator's model API keys out of every
  spawned environment, and the **git config pins** beside it
  (``services/sandbox/gitenv.py``), which take the keys that turn an ordinary `git status`
  into an execution — the filesystem monitor, the pager — back off the repository;
- the harness's destructive-command denylist (`rm`, `dd`, `mkfs`, `shutdown`, …), which
  its own README is careful to call a guardrail rather than a security boundary;
- code mode being **explicitly chosen** for a thread and bound to a project the
  operator named.

**Failures the model can act on come back as `ModelRetry`, not as a dead run.** A denied or
blocked command, a working directory an earlier command deleted, and a command the OS
refuses to spawn all return to the model so it can try something else; only what the model
could do nothing about (a host that cannot allocate a process, an oversized argument or
environment) still aborts the turn. That split is the harness's, not ours — we hand it a
`cwd` and a denylist and inherit the rest.

An allowlist of permitted programs was considered instead and rejected twice over: an agent
writing code needs whatever build tool the project uses, so any allowlist honest enough to
be useful is long enough to be meaningless, and it would still be bypassable through an
allowed interpreter. Bounding what a spawned program may *do* is the answer that covers
`make`, `npm run` and a test suite without naming any of them.

**Refused outright outside a worktree mode.** `mode_disabled_tools` already hides these
tools from every mode whose spec does not admit the `shell` category, but that is a
filter, and a filter is the wrong place for the only thing standing between an unfenced
host command and a sandbox thread. The check is here too.
"""

from __future__ import annotations

import contextlib
import os
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from pydantic_ai import AbstractToolset, FunctionToolset, RunContext, ToolsetTool
from pydantic_ai.exceptions import ApprovalRequired, ModelRetry
from pydantic_ai_harness import Shell
from pydantic_ai_harness.shell._capability import LLM_API_KEY_ENV_PATTERNS
from pydantic_ai_harness.shell._toolset import ShellToolset

from core.config import get_settings
from services.modes import mode_spec
from services.permissions import Reach, capability_of
from services.sandbox import denied_read_paths, fence, git_config_pins
from services.workspace import RunWorkspace

from .deps import RunDeps
from .rebound import WorkspaceToolset
from .workspace import run_workspace

if TYPE_CHECKING:  # pragma: no cover — the fence's own types, never imported at runtime
    from sandbox_runtime import SandboxRuntimeConfig

#: Long enough for a real build or test suite; short enough that a hung command doesn't
#: hold the turn open indefinitely. The agent can pass its own timeout per call, and any
#: genuinely long-running thing belongs in `start_command`.
_TIMEOUT_S = 300.0

#: Effectively no cap. The harness requires a positive number, but this codebase has one
#: context reduction — conversation compaction, on measured pressure — and truncating a
#: tool result is exactly what was torn out of `code_execute`. A pathological command's
#: output is caught by the run's own context-overflow stop, which says so out loud rather
#: than silently costing the model the middle of what it just asked for.
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

#: The prefix `tools/toolsets.py` will put in front of these names. Spelled here because
#: the capability extraction is keyed on the namespaced name and this file only ever sees
#: the bare one.
_NAMESPACE = "shell_"

#: A root no run will ever have. The template toolset exists to answer `get_tools`, which
#: does not depend on where a command would run, and a plausible-looking path here would
#: invite the assumption that it does.
_TEMPLATE_ROOT = Path("/nonexistent-template-root")

_WRONG_MODE = (
    "Shell commands are only available in a code conversation, which runs in a "
    "project's git worktree. This conversation runs in a container — use `code_execute` "
    "instead."
)


def _guard(name: str, ctx: RunContext[RunDeps], workspace: RunWorkspace) -> str | None:
    """Refuse outside a worktree mode; otherwise pause for approval on the first command.

    `tool_call_approved` is set on the re-invocation after an approval, so this raises
    once and then lets the command run — and a conversation-scoped grant means the
    operator is asked once per thread, not once per command.
    """
    if mode_spec(ctx.deps.mode).workspace != "worktree" or workspace.kind != "worktree":
        return _WRONG_MODE
    if name in EXECUTING_TOOLS and not ctx.tool_call_approved:
        raise ApprovalRequired()
    return None


def _toolset_for(root: Path) -> ShellToolset[RunDeps]:
    return Shell[RunDeps](
        cwd=root,
        # `cd` inside the worktree is tracked between calls, so the agent can work the
        # way a person does instead of re-prefixing every command.
        persist_cwd=True,
        default_timeout=_TIMEOUT_S,
        max_output_chars=_MAX_OUTPUT_CHARS,
        # The inherited environment, with the settings a repository must not choose for us
        # pinned over it (`services/sandbox/gitenv.py`) — otherwise `git status` in a
        # cloned worktree runs whatever that repository's own config names. Handing the
        # harness an explicit env does not lose the key filtering: `denied_env_patterns`
        # is applied over whichever base it is given, so the two compose.
        env=git_config_pins(os.environ),
        denied_env_patterns=LLM_API_KEY_ENV_PATTERNS,
    ).get_toolset()


@contextlib.contextmanager
def _cwd_capture(wanted: bool, root: Path) -> Iterator[fence.CwdCapture | None]:
    """A temp file the fenced shell records its working directory into, removed after.

    Only `run_command` wants one: it is the tool whose `cd` has to survive to the next
    call. A background command has no next call of its own, and the harness does not track
    a directory for it either.

    ``root`` rides along because the recorded directory is only adopted while it is still
    inside the worktree — see :class:`services.sandbox.fence.CwdCapture`.
    """
    if not wanted:
        yield None
        return
    handle, name = tempfile.mkstemp(prefix="odysseus-fence-cwd-")
    os.close(handle)
    path = Path(name)
    try:
        yield fence.CwdCapture(file=path, root=root)
    finally:
        path.unlink(missing_ok=True)


def _validate_as_written(shell: ShellToolset[RunDeps], command: str) -> None:
    """Put the command the *model* wrote through the harness's own checks, before fencing.

    The harness validates whatever string it is handed — a NUL byte, an interactive
    program, its destructive-command denylist — by reading the first word of it. Once a
    command is wrapped, that first word is the sandbox launcher, so every one of those
    checks would be answered about the wrong program. Running them here, against the
    command as written, is what keeps them meaning what they say.

    A `PermissionError` is the harness's own shape for "the model may try something else",
    which its decorator turns into a retry at the tool boundary; raised from here it would
    abort the turn instead, so the conversion happens here too.
    """
    try:
        shell._check_command(command)  # noqa: SLF001 — see the docstring
    except PermissionError as exc:
        raise ModelRetry(str(exc)) from exc


class _ShellToolset(WorkspaceToolset):
    """The category: two tools this file defines, and two the harness's toolset provides.

    A subclass rather than two toolsets side by side, because `start_command` and
    `check_command`/`stop_command` have to reach the *same* harness instance — the
    background process registry lives on it — and that instance is the one this class
    caches per workspace root.
    """

    def __init__(self) -> None:
        super().__init__("shell", _toolset_for(_TEMPLATE_ROOT), _toolset_for, guard=_guard)
        # A `FunctionToolset` over two bound methods, used for its schemas *and* its
        # dispatch: the model-facing definition of `reach` and the code that enforces it
        # are the same declaration, so neither can be changed without the other.
        self._declared: FunctionToolset[RunDeps] = FunctionToolset()
        self._declared.add_function(
            self.run_command,
            name="run_command",
            metadata={"code_arg_name": "command", "code_arg_language": "shell"},
        )
        self._declared.add_function(
            self.start_command,
            name="start_command",
            metadata={"code_arg_name": "command", "code_arg_language": "shell"},
        )

    @property
    def tools(self) -> dict[str, Any]:
        """The static registry `tools/catalog.py` enumerates, with the same substitution.

        The operator's settings list reads this and the model reads :meth:`get_tools`, so a
        pair that disagreed would show the operator a description of a tool the agent was
        never offered — which is the exact failure the catalog exists to prevent.
        """
        return {**super().tools, **self._declared.tools}

    async def get_tools(self, ctx: RunContext[RunDeps]) -> dict[str, ToolsetTool[RunDeps]]:
        """The harness's four, with the two executing ones replaced by the declaring pair.

        Merged rather than filtered-and-combined so the category keeps one identity and one
        order: the operator's tool list, the approval scopes and the agent's stack all read
        this mapping, and a tool that appeared in a different place in each would be four
        chances to disagree about what `shell` contains.
        """
        return {**await super().get_tools(ctx), **await self._declared.get_tools(ctx)}

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext[RunDeps],
        tool: ToolsetTool[RunDeps],
    ) -> Any:
        # Resolved from `_declared` rather than forwarded: the object handed in is whatever
        # the caller resolved, and this toolset's own dispatch has to act through the tool
        # *it* defined or the `reach` argument it added would never be validated.
        if name in EXECUTING_TOOLS:
            declared = await self._declared.get_tools(ctx)
            return await self._declared.call_tool(name, tool_args, ctx, declared[name])
        return await super().call_tool(name, tool_args, ctx, tool)

    async def run_command(
        self,
        ctx: RunContext[RunDeps],
        command: str,
        reach: Reach = "workspace",
        timeout_seconds: float | None = None,
    ) -> str:
        """Execute a shell command in the project's worktree and return its output.

        Args:
            command: The shell command to run.
            reach: How far this command needs to go. `workspace` runs it fenced to the
                worktree with no network — the right answer for builds, tests, git and
                anything reading or writing the checkout. `network` additionally allows the
                domains the operator has permitted, for installing dependencies. `host`
                lifts the fence for a command that has to act on the machine itself. A
                command that needs more than it declared fails inside the fence and says
                so; declare again rather than working around it.
            timeout_seconds: Maximum seconds to wait (default: 300).

        Returns:
            Labeled stdout/stderr output with exit code on non-zero exit.
        """
        return await self._execute(
            ctx, "run_command", command, reach, {"timeout_seconds": timeout_seconds}
        )

    async def start_command(
        self, ctx: RunContext[RunDeps], command: str, reach: Reach = "workspace"
    ) -> str:
        """Start a long-running command in the background (e.g. a server or watcher).

        Callers MUST call `stop_command(command_id)` when done to terminate the
        process and clean up temporary output files.

        Args:
            command: The shell command to run in the background.
            reach: How far this command needs to go — the same three answers
                `run_command` takes, enforced the same way.

        Returns:
            A message containing the unique command ID for later check/stop calls.
        """
        return await self._execute(ctx, "start_command", command, reach, {})

    async def _execute(
        self,
        ctx: RunContext[RunDeps],
        name: str,
        command: str,
        reach: Reach,
        extra: dict[str, Any],
    ) -> Any:
        """Bind, validate, fence, and hand the result to the harness's own tool."""
        bound = await self.bind(name, ctx)
        if isinstance(bound, str):
            return bound
        shell = cast(ShellToolset[RunDeps], bound)
        _validate_as_written(shell, command)
        # Read back off the run's memo, which `bind` has just filled: a run with no
        # workspace was refused above in words, so `None` here is only the type saying
        # what the branch above already answered.
        workspace = await run_workspace(ctx)
        profile = (
            None if workspace is None else await self._profile(name, command, reach, workspace)
        )
        if profile is None:
            return await self._dispatch(shell, name, {"command": command, **extra}, ctx)
        with _cwd_capture(name == "run_command", workspace.root) as cwd:
            fenced = await fence.wrap(command, profile, cwd=cwd)
            result = await self._dispatch(shell, name, {"command": fenced, **extra}, ctx)
        if isinstance(result, str):
            return fence.annotate(result)
        return result

    async def _dispatch(
        self,
        shell: ShellToolset[RunDeps],
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext[RunDeps],
    ) -> Any:
        """Call the harness's own tool, resolved against the instance bound to this root."""
        tools = await self._tools_for(shell, ctx)
        return await shell.call_tool(name, tool_args, ctx, tools[name])

    async def _profile(
        self, name: str, command: str, reach: Reach, workspace: RunWorkspace
    ) -> SandboxRuntimeConfig | None:
        """The fence profile this command runs under, or None to run it as written.

        **Built from the declaration, not from a judgement**, and that separation is the
        whole of it: the permission layer's stages answer *who must approve*, and this
        answers *what the boundary is*. Nothing is threaded through the park, the approval
        payload or the resume, and a call the operator approved by hand at another level is
        fenced identically, having never passed a gate at all.

        Keying it off the deterministic stage instead would hand the model the boundary as
        a lever. That stage declines `ls $(true)` and `git commit -m 'fix the parser'` for
        being *unreadable* — not for reaching anywhere — so running what it declined
        unwrapped would let any command escape the fence by being written so nothing could
        read it, and the reviewer that then allowed it was never asked about the fence.

        There are exactly two ways out and each is somebody's explicit yes. A `host`
        declaration asks for the unfenced machine, which is what the approver was shown. A
        declaration the command's own syntax **contradicts** — a `workspace` command naming
        `/etc/passwd` or a URL — was approved in the words it was read in, and fencing it to
        the reach it plainly does not have would break that act rather than bound it.

        **An empty allowed-domains list is not one of them.** A `network` declaration with
        nothing allowed still runs fenced, with no egress at all — the command fails at the
        boundary and says so, which is the whole point of the declaration. Reading the empty
        list as "no list to hold it to" and lifting the fence inverted the setting: an
        operator who empties it to reach *less* would have handed every approved networked
        command the loosest execution path there is, write confinement and the host hatch's
        own read denials included.
        """
        settings = get_settings()
        confinement = await fence.fence_available(settings)
        if not confinement.active or reach == "host":
            return None
        allowed = settings.host_command_allowed_domains
        capability = capability_of(
            f"{_NAMESPACE}{name}", {"command": command, "reach": reach}, root=workspace.root
        )
        if capability.escapes or (reach == "workspace" and capability.network):
            return None
        return fence.workspace_profile(
            workspace.root,
            fence.GitDirs.read(workspace.root),
            workspace.branch,
            allowed_domains=allowed if reach == "network" else (),
            # The host hatch's own denials, not a second list: a per-call profile replaces
            # the global one rather than narrowing it, and a command the deterministic
            # stage cleared for itself must never be fenced more loosely than one the
            # operator read and approved.
            deny_read=denied_read_paths(settings),
            allow_write=settings.worktree_command_allow_write,
            linux=sys.platform.startswith("linux"),
        )


def shell_toolset() -> AbstractToolset[RunDeps]:
    """The `shell` category, built once at app assembly and shared by every run."""
    return _ShellToolset()
