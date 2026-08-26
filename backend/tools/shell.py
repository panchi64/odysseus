"""The `shell` category — running commands in a coding conversation's worktree.

`pydantic_ai_harness`'s `Shell`: `run_command` (blocking), `start_command` /
`check_command` / `stop_command` (background), so a dev server or a long test run is a
process the agent checks on rather than a turn that blocks for ten minutes. Rebound per
run to the project's worktree, the same way `files` is.

**This is not `code_run_host_command`, and the difference matters.** That tool wraps every
command in `sandbox-runtime`, which fences the filesystem — `data_dir` in particular — and
it stays exactly as it is. `Shell` spawns processes itself; there is no seam to route
through the fence. So what protects the operator here is not an OS boundary:

- the **worktree and its branch** — the agent's edits land on a throwaway branch, and the
  operator's own checkout is written only by a merge they approve;
- **approval on the first command** of a conversation, grantable for the thread, so an
  agent cannot start executing on the host without the operator having said yes once;
- **`denied_env_patterns`**, which keeps the operator's model API keys out of every
  spawned environment;
- the harness's destructive-command denylist (`rm`, `dd`, `mkfs`, `shutdown`, …), which
  its own README is careful to call a guardrail rather than a security boundary;
- coding mode being **explicitly chosen** for a thread and bound to a project the
  operator named.

An allowlist was considered instead of the approval gate and rejected: a coding agent
needs whatever build tool the project uses, so any allowlist honest enough to be useful is
long enough to be meaningless, and it would still be bypassable through an allowed
interpreter. One deliberate "yes, run commands in this project" is a stronger statement
and a far smaller nuisance.

**Refused outright outside coding mode.** `mode_disabled_tools` already hides these tools
from a chat run, but that is a filter, and a filter is the wrong place for the only thing
standing between an unfenced host command and a chat thread. The check is here too.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_ai import AbstractToolset, RunContext
from pydantic_ai.exceptions import ApprovalRequired
from pydantic_ai_harness import Shell
from pydantic_ai_harness.shell._capability import LLM_API_KEY_ENV_PATTERNS

from services.workspace import RunWorkspace

from .deps import RunDeps
from .rebound import WorkspaceToolset

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

_WRONG_MODE = (
    "Shell commands are only available in a coding conversation, which runs in a "
    "project's git worktree. This is a chat conversation — use `code_execute` instead."
)


def _guard(name: str, ctx: RunContext[RunDeps], workspace: RunWorkspace) -> str | None:
    """Refuse outside coding mode; otherwise pause for approval on the first command.

    `tool_call_approved` is set on the re-invocation after an approval, so this raises
    once and then lets the command run — and a conversation-scoped grant means the
    operator is asked once per thread, not once per command.
    """
    if ctx.deps.mode != "coding" or workspace.kind != "worktree":
        return _WRONG_MODE
    if name in EXECUTING_TOOLS and not ctx.tool_call_approved:
        raise ApprovalRequired()
    return None


def _toolset_for(root: Path) -> AbstractToolset[RunDeps]:
    return Shell[RunDeps](
        cwd=root,
        # `cd` inside the worktree is tracked between calls, so the agent can work the
        # way a person does instead of re-prefixing every command.
        persist_cwd=True,
        default_timeout=_TIMEOUT_S,
        max_output_chars=_MAX_OUTPUT_CHARS,
        denied_env_patterns=LLM_API_KEY_ENV_PATTERNS,
    ).get_toolset()


def shell_toolset() -> AbstractToolset[RunDeps]:
    """The `shell` category, built once at app assembly and shared by every run."""
    return WorkspaceToolset(
        "shell",
        _toolset_for(Path("/nonexistent-template-root")),
        _toolset_for,
        guard=_guard,
    )
