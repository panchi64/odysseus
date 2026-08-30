"""The `project` category — what the agent is working in.

Read-only and ungated. Two tools, both answering questions the model would otherwise
guess at: *what projects exist* and *which one is this conversation in*. Neither reveals
anything the operator did not already put on screen, and neither changes state — creating
or activating a project is the operator's act, not the agent's, so there is no tool for
it here.

The active project comes from ``ctx.deps.project_id``, which the chat layer resolves from
the **conversation's** binding rather than the live request: a run must keep reporting the
project it started in even if the operator switches away mid-turn.
"""

from __future__ import annotations

from pydantic_ai import FunctionToolset, RunContext

from services.projects import ProjectStore
from tools.deps import RunDeps

_UNAVAILABLE = "Projects are unavailable in this deployment."


def project_toolset() -> FunctionToolset[RunDeps]:
    toolset = FunctionToolset[RunDeps]()

    # Named explicitly rather than by the function name: the namespaced tool the model
    # sees is `project_list`, and shadowing the `list` builtin to get there would be a
    # poor trade for a name the decorator can simply be told.
    @toolset.tool(name="list")
    async def list_projects(ctx: RunContext[RunDeps]) -> dict:
        """List the operator's projects — the directories they work in.

        Returns each project's name and absolute path on the operator's machine, and
        which one (if any) this conversation is bound to.
        """
        store = ctx.deps.caps.get_optional(ProjectStore)
        if store is None:
            return {"available": False, "detail": _UNAVAILABLE}
        views = await store.list(ctx.deps.owner_id)
        return {
            "available": True,
            "active_project_id": ctx.deps.project_id,
            "projects": [
                {
                    "id": v.id,
                    "name": v.name,
                    "path": v.root_path,
                    "is_git_repo": v.probe.is_git_repo,
                    "uncommitted_changes": v.probe.uncommitted_changes,
                }
                for v in views
            ],
        }

    @toolset.tool(name="active")
    async def active_project(ctx: RunContext[RunDeps]) -> dict:
        """The project this conversation is working in, if any.

        In code mode this is the project whose git worktree your file and shell tools
        act on. Uncommitted changes in the operator's own checkout are **not** visible to
        you — your worktree branches from the project's base ref — so if their tree is
        dirty, say so rather than assuming you can see their latest edits.
        """
        store = ctx.deps.caps.get_optional(ProjectStore)
        if store is None:
            return {"available": False, "detail": _UNAVAILABLE}
        if ctx.deps.project_id is None:
            return {"available": True, "project": None, "mode": ctx.deps.mode}
        view = await store.get(ctx.deps.owner_id, ctx.deps.project_id)
        return {
            "available": True,
            "mode": ctx.deps.mode,
            "project": {
                "id": view.id,
                "name": view.name,
                "path": view.root_path,
                "base_ref": view.base_ref,
                "is_git_repo": view.probe.is_git_repo,
                "uncommitted_changes": view.probe.uncommitted_changes,
            },
        }

    return toolset
