"""Projects — the operator's working directories, and the scope the app filters by.

The store is exported as both a service (the worktree layer and the scoped list queries
resolve it) and a capability (the `project` tools read it). The `WorktreeManager` goes out
the same way, because code mode's workspace resolver runs *inside* a run and reaches it
through the bag like any other capability.

The host file picker (`/host/file-picker`) rides along here: it is stateless and owns no
service, and Projects — where the operator names an absolute directory on their own
machine — is what still asks for a host path.
"""

from __future__ import annotations

from core.api_scopes import ScopeClaim
from harness.manifest import FeatureManifest, FeatureRuntime, HarnessContext
from routes import host as host_routes
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
    #
    # From `ctx.settings`, never `get_settings()`: this app has its own Settings (a test
    # app's are a throwaway temp dir), and reading the process-global here had every test
    # cutting real worktrees into the operator's own home directory.
    worktrees = WorktreeManager(ctx.settings.worktrees_dir)
    return FeatureRuntime(
        services=(store, worktrees),
        capabilities=(store, worktrees),
        state={"projects": store, "worktrees": worktrees},
    )


MANIFEST = FeatureManifest(
    name="projects",
    routers=(project_routes.router, worktree_routes.router, host_routes.router),
    # `/host` is deliberately unclaimed: opening a native dialog on the operator's
    # machine — and reading back an arbitrary absolute path — is not something an
    # inbound token should be able to do, so it stays denied by default.
    api_scopes=(ScopeClaim("projects", ("/projects", "/worktrees")),),
    toolsets=(("project", project_toolset),),
    build=_build,
)
