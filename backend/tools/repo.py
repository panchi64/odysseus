"""The `repo` category — what a codebase already says about how to work in it.

`pydantic_ai_harness`'s `RepoContext`, split across the two seams this codebase has for
model-facing text:

- **the instructions half** — a project's own `CLAUDE.md` / `AGENTS.md`, loaded from the
  worktree root and handed to the model as standing instructions. Registered as an
  `InstructionProvider` rather than through the capability's `get_instructions`, because
  the capability is constructed once at app assembly and the workspace is per-run; a
  provider re-resolves each turn and can therefore read the run's own worktree. The
  content is static per project, so it stays cache-stable at the prompt head even though
  it is resolved dynamically.
- **the inventory tool** — reports where the repo keeps its coding-assistant assets
  (`.claude/`, `.agents/`, `.codex/` and their `skills/`, `agents/`, `settings.json`). It
  locates them; reading them is the file tools' job. Rebound per run like every other
  workspace-rooted category.

Both are no-ops outside coding mode: a chat conversation's sandbox workspace is scratch
space, and there is no repository in it to have an opinion.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_ai import AbstractToolset, RunContext
from pydantic_ai_harness import RepoContext

from services.projects.worktree import WorktreeBusyError

from .deps import RunDeps
from .rebound import WorkspaceToolset
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
    )


async def repo_instructions(ctx: RunContext[RunDeps]) -> str:
    """The project's own instruction files, as standing instructions for the run."""
    if ctx.deps.mode != "coding":
        return ""
    try:
        workspace = await run_workspace(ctx)
    except WorktreeBusyError:
        return ""
    if workspace is None or workspace.kind != "worktree":
        return ""
    return _capability(workspace.root).get_instructions() or ""


def _toolset_for(root: Path) -> AbstractToolset[RunDeps]:
    toolset = _capability(root).get_toolset()
    assert toolset is not None  # `expose_inventory_tool` defaults on
    return toolset


def repo_toolset() -> AbstractToolset[RunDeps]:
    """The `repo` category, built once at app assembly and shared by every run."""
    return WorkspaceToolset(
        "repo", _toolset_for(Path("/nonexistent-template-root")), _toolset_for
    )
