"""Projects — the operator's working directories, and the scope the app filters by.

The store is exported as both a service (the worktree layer and the scoped list queries
resolve it) and a capability (the `project` tools read it).
"""

from __future__ import annotations

from core.api_scopes import ScopeClaim
from harness.manifest import FeatureManifest, FeatureRuntime, HarnessContext
from routes import projects as project_routes
from services.projects import ProjectStore
from services.settings_store import SettingsStore
from tools.projects import project_toolset


async def _build(ctx: HarnessContext) -> FeatureRuntime:
    store = ProjectStore(ctx.engine, ctx.vault, ctx.services.get(SettingsStore))
    return FeatureRuntime(
        services=(store,),
        capabilities=(store,),
        state={"projects": store},
    )


MANIFEST = FeatureManifest(
    name="projects",
    routers=(project_routes.router,),
    api_scopes=(ScopeClaim("projects", ("/projects",)),),
    toolsets=(("project", project_toolset),),
    build=_build,
)
