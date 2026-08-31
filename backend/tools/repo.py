"""The `repo` category — what a codebase already says about how to work in it.

`pydantic_ai_harness`'s `RepoContext`, split across the two seams this codebase has for
model-facing text:

- **the instructions half** — a project's own `CLAUDE.md` / `AGENTS.md`, loaded from the
  worktree root and handed to the model as standing instructions. Registered as an
  `InstructionProvider` rather than through the capability's `get_instructions`, because
  the capability is constructed once at app assembly and the workspace is per-run; a
  provider re-resolves each turn and can therefore read the run's own worktree. The
  content is static per project, so it stays cache-stable at the prompt head even though
  it is resolved dynamically. The loading itself is ours rather than the capability's
  (`repo_instructions.py`) for one reason: it has to be *budgeted*, and the capability
  reads whatever is on disk.
- **the inventory tool** — reports where the repo keeps its coding-assistant assets
  (`.claude/`, `.agents/`, `.codex/` and their `skills/`, `agents/`, `settings.json`). It
  locates them; reading them is the file tools' job. Rebound per run like every other
  workspace-rooted category.

Both are no-ops outside a worktree mode: a sandbox workspace is scratch space, and there
is no repository in it to have an opinion.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_ai import AbstractToolset, RunContext
from pydantic_ai_harness import RepoContext

from services.modes import mode_spec
from services.projects.worktree import WorktreeBusyError

from .deps import RunDeps
from .rebound import WorkspaceToolset
from .repo_instructions import repo_instruction_text
from .workspace import run_workspace

#: The tool's own name inside the toolset; namespaced to `repo_inventory_agent_context`.
INVENTORY_TOOL = "inventory_agent_context"


def _capability(root: Path) -> RepoContext[RunDeps]:
    return RepoContext[RunDeps](
        workspace_dir=root,
        # No walk-up: `home_dir=None` scans the worktree only. Climbing above it would
        # read instruction files from directories the operator never put in a project —
        # ultimately their home directory — which is not something to do quietly.
        home_dir=None,
        # Off: it hooks the file tools' results to surface a nested directory's
        # instruction file, and those results ride into context untrimmed here.
        nested_traversal=False,
        # Off because it is *ours*: the capability would load the instruction files whole,
        # and the prompt head is the one place a file of unbounded size must not land.
        # `repo_instructions.py` does the same load under a byte budget; what remains of
        # the capability's own brief is the inventory tool's one-line hint.
        autoload_instructions=False,
    )


async def repo_instructions(ctx: RunContext[RunDeps]) -> str:
    """The project's own instruction files, as standing instructions for the run."""
    if mode_spec(ctx.deps.mode).workspace != "worktree":
        return ""
    try:
        workspace = await run_workspace(ctx)
    except WorktreeBusyError:
        return ""
    if workspace is None or workspace.kind != "worktree":
        return ""
    return _brief(workspace.root)


def _brief(root: Path) -> str:
    """The budgeted instruction files, then the capability's own inventory hint — the
    same order and the same joiner its `get_instructions` uses, so moving the loading out
    from under it changed what is *bounded*, not what the model reads."""
    parts = (repo_instruction_text(root), _capability(root).get_instructions() or "")
    return "\n\n".join(part for part in parts if part)


def _toolset_for(root: Path) -> AbstractToolset[RunDeps]:
    toolset = _capability(root).get_toolset()
    assert toolset is not None  # `expose_inventory_tool` defaults on
    return toolset


def repo_toolset() -> AbstractToolset[RunDeps]:
    """The `repo` category, built once at app assembly and shared by every run."""
    return WorkspaceToolset(
        "repo", _toolset_for(Path("/nonexistent-template-root")), _toolset_for
    )
