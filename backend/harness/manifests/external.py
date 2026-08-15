"""External tools — registered MCP servers (`MCP-*`), configured connectors
(`INTEG-*`) and the per-tool trust policy they share (`AE-3.6`), as one handle.

The factory is the only way to build it, so both sources are guaranteed the *same*
policy store. MCP connections are opened per run, not held here.
"""

from __future__ import annotations

from harness.manifest import FeatureManifest, FeatureRuntime, HarnessContext
from routes import integrations as integrations_routes
from routes import mcp as mcp_routes
from services.external_tools import build_external_tools


async def _build(ctx: HarnessContext) -> FeatureRuntime:
    external = build_external_tools(ctx.engine, ctx.vault)
    return FeatureRuntime(services=(external,), state={"external": external})


MANIFEST = FeatureManifest(
    name="external",
    routers=(mcp_routes.router, integrations_routes.router),
    build=_build,
)
