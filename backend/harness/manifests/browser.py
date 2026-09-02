"""The browser-control feature — the agent drives a real page, and the operator watches.

Deliberately a *separate* manifest from `web`, and deliberately built after it: the
browser it drives is the one `web` already brought up, reached over that container's CDP
endpoint. So this feature owns sessions, not a browser — which is why its shutdown hook
registers here (draining sessions) while the container's stays with `web`, and why the
ordering matters: registered after `web`'s, so it runs before it and no session is left
attached to a browser that has already gone.
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
from services.browser import BrowserSessionManager
from services.webfetch import ManagedBrowser
from tools.browse import NETWORK_TOOLS, browse_toolset


async def _build(ctx: HarnessContext) -> FeatureRuntime:
    settings = ctx.settings
    sessions = BrowserSessionManager(
        ctx.services.get(ManagedBrowser),
        idle_ttl_s=settings.browser_control_idle_ttl_s,
        reap_interval_s=settings.browser_control_reap_interval_s,
        max_live=settings.browser_control_max_live,
        frame_width=settings.browser_control_frame_width,
        frame_height=settings.browser_control_frame_height,
        frame_quality=settings.browser_control_frame_quality,
    )
    await ctx.lifecycle.start("browser-sessions", start=sessions.start, stop=sessions.stop)
    return FeatureRuntime(
        services=(sessions,),
        capabilities=(sessions,),
        state={"browser_sessions": sessions},
    )


MANIFEST = FeatureManifest(
    name="browser",
    # The managed browser is web's to build; this resolves it from the container.
    after=("web",),
    routers=(browser_routes.router,),
    # Asking whether a thread has a live browser is part of reading that thread.
    api_scopes=(ScopeClaim("chat", ("/browser/session",)),),
    # The frame stream is auth-exempt: the unguessable token in the path is the
    # credential (a WebSocket can carry no auth header), and it serves only pixels of
    # pages the agent opened. Scoped to `/browser/stream` on purpose — `/browser/session`
    # answers about the operator's conversations and stays behind the gate.
    public_prefixes=("/browser/stream",),
    # No kill-switch of its own, deliberately. `web_fetch_enabled` already decides whether
    # a browser comes up at all, and a second switch that withheld the *category* would
    # make the operator's tool catalog disagree with the agent's real stack — the exact
    # divergence the namespacing exists to prevent. With no browser to attach to, the
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
