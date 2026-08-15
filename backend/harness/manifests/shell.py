"""The Operator Shell (`SHELL-1..3`) — a host PTY streamed to the browser,
agent-unreachable by construction (imported only by its route and this wiring;
enforced by an import-guard test).

`shell_enabled` is the kill-switch: when off, this manifest is skipped entirely —
the router isn't registered (`/shell/*` is simply 404) and the service never
exists. Killing every live session the instant the vault locks rides the vault's
own on-lock callback registry, not the auth route knowing the shell exists.
"""

from __future__ import annotations

from core.auth import AuthManager
from core.config import Settings
from core.ratelimit import RateLimiter
from harness.manifest import FeatureManifest, FeatureRuntime, HarnessContext
from routes import shell as shell_routes
from services.host_shell import ShellService


async def _build(ctx: HarnessContext) -> FeatureRuntime:
    # Its own rate limiter throttles password attempts against the host-mode grant
    # endpoint, like uploads throttle theirs.
    rate_limiter = RateLimiter(
        rate_per_second=ctx.settings.shell_auth_rate_per_minute / 60.0,
        burst=ctx.settings.shell_auth_rate_burst,
    )
    shell = ShellService(
        settings=ctx.settings,
        vault=ctx.vault,
        auth_manager=ctx.services.get(AuthManager),
    )
    ctx.vault.register_on_lock(shell.kill_all)
    ctx.lifecycle.on_stop("shell", shell.stop)
    return FeatureRuntime(
        services=(shell,),
        state={"shell": shell, "shell_auth_rate_limiter": rate_limiter},
    )


def _enabled(settings: Settings) -> bool:
    return settings.shell_enabled


MANIFEST = FeatureManifest(
    name="shell",
    routers=(shell_routes.router,),
    enabled=_enabled,
    build=_build,
)
