"""`run_workspace(ctx)` — the workspace resolver, as a tool sees it.

`services/workspace.py` holds the resolution; this is the half that reads it off
`RunDeps` and the capability bag, so a tool asks one question and gets one answer rather
than each reaching for `SandboxSessionManager` and branching on mode itself.

The answer is memoised **on the run's own deps**, not in a module-level cache: a code
turn's first call does real work (`git worktree add`, a branch checkout) and a turn makes
many file-tool calls, but the memo must die with the run rather than outlive it in a
global. Only a successful resolution is kept — a sandbox that failed to open may open on
the next call, and the failure path costs nothing to retry.
"""

from __future__ import annotations

from pydantic_ai import RunContext

from services.modes import mode_spec
from services.projects.store import ProjectStore
from services.projects.worktree import WorktreeManager
from services.sandbox import SandboxSessionManager
from services.workspace import RunWorkspace, resolve_workspace

from .deps import RunDeps

# The words the model gets when there is nowhere to work, in both modes. Kept identical
# to `code_execute`'s so a missing runtime reads as one fact about one machine.
NO_WORKSPACE = (
    "Your computer is unavailable right now: no runtime is configured. Files cannot "
    "be read or written, and nothing will run on the operator's host."
)

NO_PROJECT = (
    "This code conversation has no project workspace: its project is missing or its "
    "git worktree could not be opened. Ask the operator to check the project's folder."
)


async def run_workspace(ctx: RunContext[RunDeps]) -> RunWorkspace | None:
    """Where this run's file work happens, or None when it has nowhere to work.

    None is the degrade signal every caller already knows how to handle: a sandbox mode
    with no runtime, a worktree mode with no project bound. A busy worktree raises
    instead — the operator has to be told, not quietly given a different filesystem.
    """
    deps = ctx.deps
    if deps.workspace is not None:
        return deps.workspace

    workspace = await resolve_workspace(
        mode=deps.mode,
        project_id=deps.project_id,
        conversation_id=deps.conversation_id,
        sandbox_key=deps.sandbox_key,
        owner_id=deps.owner_id,
        sessions=deps.caps.get_optional(SandboxSessionManager),
        projects=deps.caps.get_optional(ProjectStore),
        worktrees=deps.caps.get_optional(WorktreeManager),
        # The run claims its container for as long as it lasts, not for the length of
        # one tool call: the live-session cap would otherwise be free to seal a workspace
        # away between two of them, and the seal drops exactly what an install or a clone
        # just put there.
        holder=deps.run,
    )
    deps.workspace = workspace
    return workspace


def unavailable(deps: RunDeps) -> str:
    """The right "no workspace" sentence for the mode the run is in."""
    return NO_PROJECT if mode_spec(deps.mode).workspace == "worktree" else NO_WORKSPACE
