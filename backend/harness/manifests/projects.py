"""Projects — the operator's working directories, and the scope the app filters by.

The store is exported as both a service (the worktree layer and the scoped list queries
resolve it) and a capability (the `project` tools read it). The `WorktreeManager` goes out
the same way, because coding mode's workspace resolver runs *inside* a run and reaches it
through the bag like any other capability.
"""

from __future__ import annotations

from core.api_scopes import ScopeClaim
from core.config import get_settings
from harness.manifest import FeatureManifest, FeatureRuntime, HarnessContext
from routes import projects as project_routes
from routes import worktrees as worktree_routes
from services.projects import ProjectStore, WorktreeManager
from services.settings_store import SettingsStore
from tools.projects import project_toolset


async def _build(ctx: HarnessContext) -> FeatureRuntime:
    store = ProjectStore(ctx.engine, ctx.vault, ctx.services.get(SettingsStore))
    # Outside `data_dir` on purpose — an approved host command is fenced against reads of
    # the whole data directory, so a worktree beneath it would be unreadable by the very
    # shell that has to build and test in it (`services/projects/worktree.py`).
    worktrees = WorktreeManager(get_settings().worktrees_dir)
    return FeatureRuntime(
        services=(store, worktrees),
        capabilities=(store, worktrees),
        state={"projects": store, "worktrees": worktrees},
    )


MANIFEST = FeatureManifest(
    name="projects",
    routers=(project_routes.router, worktree_routes.router),
    api_scopes=(ScopeClaim("projects", ("/projects", "/worktrees")),),
    toolsets=(("project", project_toolset),),
    build=_build,
)
