"""The browser-control feature — the agent drives a real page, in the operator's window.

This feature owns *two* things now: the visible Chromium on the host (and the SSRF proxy
it is pointed at), and the per-conversation sessions attached to it. It no longer depends
on `web` — the browser it drives is its own, not the container web fetch renders in — so
the build order is free again.

Both register a stop here, the window's *before* the sessions': the lifecycle unwinds in
reverse, so the sessions drain first and none is left attached to a window that is already
closing. Neither has anything to start — the window is launched lazily on the first
acquire, so a run of the app in which nobody browses opens none.
"""

from __future__ import annotations

from core.api_scopes import ScopeClaim
from harness.manifest import (
    DormantCategory,
    FeatureManifest,
    FeatureRuntime,
    HarnessContext,
)
from routes import browser as browser_routes
from services.browser import BrowserSessionManager, HostBrowser
from tools.browse import NETWORK_TOOLS, browse_toolset


async def _build(ctx: HarnessContext) -> FeatureRuntime:
    settings = ctx.settings
    host = HostBrowser(launch_timeout_s=settings.browser_control_launch_timeout_s)
    ctx.lifecycle.on_stop("host-browser", host.stop)
    sessions = BrowserSessionManager(
        host,
        idle_ttl_s=settings.browser_control_idle_ttl_s,
        reap_interval_s=settings.browser_control_reap_interval_s,
        max_live=settings.browser_control_max_live,
        state_dir=settings.browser_control_state_dir,
    )
    await ctx.lifecycle.start("browser-sessions", start=sessions.start, stop=sessions.stop)
    return FeatureRuntime(
        services=(sessions,),
        capabilities=(sessions,),
        state={"browser_sessions": sessions},
    )


MANIFEST = FeatureManifest(
    name="browser",
    routers=(browser_routes.router,),
    # Asking whether a thread has a live browser — and asking for one — is part of working
    # in that thread.
    api_scopes=(ScopeClaim("chat", ("/browser/session",)),),
    # No kill-switch of its own, deliberately. A switch that withheld the *category* would
    # make the operator's tool catalog disagree with the agent's real stack — the exact
    # divergence the namespacing exists to prevent. When no window can be opened, the
    # tools assemble and degrade, like every other capability here.
    toolsets=(("browse", browse_toolset),),
    # By far the most expensive category in the catalog, and the one the average turn
    # never opens — eighteen tools whose schemas would otherwise ride in every request
    # of every conversation, whether or not a page is ever loaded.
    dormant=(
        DormantCategory(
            "browse",
            "drive a real browser — navigate, click, type, read pages behind logins, "
            "inspect network and console",
        ),
    ),
    network_tools=NETWORK_TOOLS,
    build=_build,
)
