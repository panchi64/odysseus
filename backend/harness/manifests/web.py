"""The web feature — managed search, page fetch, and the offline mode that owns
both of their containers.

Search queries the backend's own SearXNG (zero operator setup; an enabled provider
in the encrypted registry overrides it). Fetch renders every page in a
containerized headless browser before extraction — the open web is treated as
always-dynamic. Offline mode probes connectivity first and owns bringing both
containers up/down, so a host that boots offline never launches the heavy browser.
"""

from __future__ import annotations

import httpx

from harness.manifest import FeatureManifest, FeatureRuntime, HarnessContext
from prompts.utility import DISTILL_INSTRUCTIONS
from routes import offline as offline_routes
from routes import search as search_routes
from routes.deps import OPERATOR_ID
from services.offline import OfflineModeService
from services.registry import ModelRegistry
from services.search import SearchService
from services.searxng import ManagedSearxng
from services.settings_store import SettingsStore
from services.webfetch import BrowserFetcher, ManagedBrowser, WebDistiller


async def _build(ctx: HarnessContext) -> FeatureRuntime:
    settings = ctx.settings
    registry = ctx.services.get(ModelRegistry)
    # Managed web search — the backend runs its own SearXNG (same container runtime
    # as the sandbox). The container is not started here: the offline-mode service
    # (below) owns bringing both web containers up — probe-first. Its stop registers
    # before the monitor's, so the monitor stops first and never fights the teardown.
    searxng = ManagedSearxng(
        enabled=settings.searxng_enabled,
        image=settings.searxng_image,
        data_dir=settings.data_dir,
        startup_timeout_s=settings.searxng_startup_timeout_s,
        external_base_url=settings.searxng_base_url,
        runtime_pref=settings.sandbox_runtime,
    )
    ctx.lifecycle.on_stop("searxng", searxng.stop)
    # The web outbound client does NOT follow redirects: an unguarded redirect off
    # the JSON API would be an SSRF hole, so the search path simply refuses one.
    web_client = httpx.AsyncClient(follow_redirects=False)
    ctx.lifecycle.on_stop("web-client", web_client.aclose)
    search = SearchService(
        ctx.engine,
        ctx.vault,
        http_client=web_client,
        managed_url=lambda: searxng.base_url,
        timeout_s=settings.web_search_timeout_s,
        result_limit=settings.web_search_result_limit,
    )
    # Web fetch — a containerized headless Chromium + the render-and-extract
    # fetcher. Bring-up is best-effort: no runtime / a failed pull leaves the
    # browser unavailable and web fetch degrades, like managed search.
    browser = ManagedBrowser(
        enabled=settings.web_fetch_enabled,
        image=settings.web_fetch_image,
        startup_timeout_s=settings.web_fetch_startup_timeout_s,
        concurrency=settings.web_fetch_concurrency,
        user_agent=settings.web_fetch_user_agent,
        locale=settings.web_fetch_locale,
        timezone_id=settings.web_fetch_timezone,
        cookie_ttl_s=settings.web_fetch_cookie_ttl_s,
        cookie_max=settings.web_fetch_cookie_max,
        proxy_image=settings.web_fetch_proxy_image,
        runtime_pref=settings.sandbox_runtime,
    )
    ctx.lifecycle.on_stop("browser", browser.stop)
    # Goal-aware distillation of oversized pages: a closure resolves the utility
    # model (the background-work rule — utility, degrade to main, reasoning off)
    # fresh per call, so it respects registry changes and keeps the engine layer out
    # of services/webfetch.
    distiller: WebDistiller | None = None
    if settings.web_fetch_distill_enabled:

        async def _resolve_distill_model():
            resolved = await registry.resolve_background(owner_id=OPERATOR_ID)
            return resolved.model, resolved.reasoning_off

        distiller = WebDistiller(
            resolve_model=_resolve_distill_model,
            instructions=DISTILL_INSTRUCTIONS,
            window_tokens=settings.web_fetch_distill_window_tokens,
            max_windows=settings.web_fetch_distill_max_windows,
            timeout_s=settings.web_fetch_distill_timeout_s,
        )
    fetcher = BrowserFetcher(
        browser=browser,
        timeout_s=settings.web_fetch_timeout_s,
        wait_until=settings.web_fetch_wait_until,
        render_wait_ms=settings.web_fetch_render_wait_ms,
        max_bytes=settings.web_fetch_max_bytes,
        min_chars=settings.web_fetch_min_chars,
        min_interval_s=settings.web_fetch_min_interval_s,
        challenge_waits=settings.web_fetch_challenge_waits,
        challenge_wait_ms=settings.web_fetch_challenge_wait_ms,
        output_max_tokens=settings.web_fetch_output_max_tokens,
        pdf_max_bytes=settings.web_fetch_pdf_max_bytes,
        pdf_max_pages=settings.web_fetch_pdf_max_pages,
        http_client=web_client,
        settle_checks=settings.web_fetch_settle_checks,
        settle_wait_ms=settings.web_fetch_settle_wait_ms,
        settle_min_chars=settings.web_fetch_settle_min_chars,
        distiller=distiller,
    )

    # Offline mode — owns both web containers' lifecycle. Probe-first at boot, then
    # watches the link and suspends/resumes them as connectivity comes and goes. The
    # operator can also force offline manually; both switches persist.
    async def _assume_online() -> bool:
        return True

    offline = OfflineModeService(
        searxng=searxng,
        browser=browser,
        settings_store=ctx.services.get(SettingsStore),
        owner_id=OPERATOR_ID,
        anchors=settings.offline_anchors,
        interval_s=settings.offline_check_interval_s,
        timeout_s=settings.offline_check_timeout_s,
        fail_threshold=settings.offline_fail_threshold,
        recover_threshold=settings.offline_recover_threshold,
        auto_default=settings.offline_auto_default,
        # Probing off ⇒ assume online (no network); only the manual switch acts.
        probe=None if settings.offline_check_enabled else _assume_online,
    )
    await ctx.lifecycle.start("offline", start=offline.start, stop=offline.stop)
    return FeatureRuntime(
        services=(searxng, search, browser, fetcher, offline),
        state={
            "searxng": searxng,
            "web_client": web_client,
            "search": search,
            "browser": browser,
            "fetcher": fetcher,
            "offline": offline,
        },
    )


MANIFEST = FeatureManifest(
    name="web",
    routers=(search_routes.router, offline_routes.router),
    build=_build,
)
