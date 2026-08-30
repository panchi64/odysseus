"""ManagedBrowser — the headless Chromium the web fetcher renders pages in, isolated in
a container.

Rendering a page means executing its untrusted JavaScript, so the browser must not run in
the backend process. It runs in its own loopback-bound container (the Docker/Podman
runtime the sandbox and managed SearXNG already use) and we drive it over the Chrome
DevTools Protocol via Playwright ``connect_over_cdp``. Two payoffs over an in-process
browser: untrusted page JS is isolated from the host, and the container's separate network
namespace keeps it off the host's own loopback. CDP is version-tolerant, so the image
tracks ``:latest`` (refreshed each boot by :func:`ensure_image`) without being pinned to
the Python client's Playwright version.

**SSRF is enforced by a proxy sidecar, not in-browser interception.** The browser is
pointed at a CONNECT/HTTP proxy (``--proxy-server``) that runs in a second container sharing
the browser's network namespace; it resolves each destination, pins the public IP, and
refuses non-public ones (see :mod:`services.webfetch.proxy_script`). Enforcing in the
browser via Playwright ``context.route`` would enable CDP's Fetch domain, which bot walls
detect and hard-block — the proxy keeps the policy while looking like an ordinary browser.

Bring-up is **best-effort and non-fatal** (mirrors :class:`services.searxng.ManagedSearxng`):
no container runtime, a failed pull, or a browser/proxy that never comes up leaves
:attr:`available` False and web fetch degrades — it never blocks app startup. The work runs
in a background task so the app boots immediately. The proxy is required (fail-closed: no
proxy ⇒ unavailable, never an unguarded fetch). Each fetch gets a fresh, stealthed context;
total concurrency is bounded.
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.parse
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright

from services.sandbox import (
    await_listening,
    detached_run_argv,
    discover_runtime,
    ensure_image,
    force_remove_container,
    published_host_port,
    run_subprocess,
)
from services.sandbox.base import SandboxError

from .cookies import DomainCookieJar
from .stealth import (
    INIT_SCRIPT,
    LAUNCH_FLAGS,
    context_options,
    realistic_user_agent,
    user_agent_override,
)

logger = logging.getLogger(__name__)

# The one container we name, the CDP port it exposes inside it, and conservative caps —
# a browser is heavier than SearXNG, and Chromium crashes on a tiny /dev/shm.
_CONTAINER = "odysseus-webfetch"
_INTERNAL_PORT = 9222
_MEMORY = "2g"
_SHM_SIZE = "1g"
_PIDS_LIMIT = 1024

# The SSRF-enforcing proxy sidecar: a second container that joins the browser's network
# namespace and that the browser is pointed at with --proxy-server. Enforcing SSRF here
# (out of the browser) instead of via Playwright request interception is deliberate —
# interception enables CDP's Fetch domain, which bot walls detect and hard-block. The port
# is loopback-only inside the shared namespace; the script is mounted read-only into a stock
# python image (it imports stdlib only, none of our code).
_PROXY_CONTAINER = "odysseus-webfetch-proxy"
_PROXY_PORT = 3128
_PROXY_SCRIPT = Path(__file__).with_name("proxy_script.py").resolve()
# Force EVERY request through the proxy — including loopback (<-loopback> drops Chrome's
# implicit localhost bypass), so a page can't reach the CDP port in the shared namespace.
_PROXY_FLAGS = [f"--proxy-server=127.0.0.1:{_PROXY_PORT}", "--proxy-bypass-list=<-loopback>"]


class ManagedBrowser:
    """Owns the lifecycle of the backend's containerized headless Chromium.

    :attr:`available` is False until the container is up and the CDP connection is live
    (or forever, if no runtime is present); callers check it and degrade. ``user_agent``
    empty ⇒ derive a realistic one from the engine version. ``runtime_pref`` pins
    docker/podman (shared with the sandbox); ``None`` auto-detects."""

    def __init__(
        self,
        *,
        enabled: bool,
        image: str,
        startup_timeout_s: float,
        concurrency: int,
        user_agent: str,
        locale: str,
        timezone_id: str,
        cookie_ttl_s: float = 0.0,
        cookie_max: int = 2000,
        proxy_image: str = "python:alpine",
        runtime_pref: str | None = None,
    ) -> None:
        self._enabled = enabled
        self._image = image
        self._proxy_image = proxy_image
        self._proxy_up = False  # the SSRF proxy is listening — gates availability (fail-closed)
        self._startup_timeout_s = startup_timeout_s
        self._sem = asyncio.Semaphore(max(1, concurrency))
        self._user_agent_override = user_agent
        self._locale = locale
        self._timezone_id = timezone_id
        # Shared across fetches so a solved challenge's clearance cookie carries forward;
        # None disables (fresh, cookieless context every fetch — the prior behaviour).
        self._jar = DomainCookieJar(ttl_s=cookie_ttl_s, max_entries=cookie_max) if (
            cookie_ttl_s > 0
        ) else None
        self._runtime_pref = runtime_pref
        self._runtime: str | None = None
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        # The container's CDP endpoint, kept after bring-up so a *second* client can
        # attach to the same Chromium instead of starting one of its own — the agent's
        # controllable browser (`services/browser`) does exactly that, inheriting this
        # container's isolation and its SSRF proxy rather than duplicating both.
        self._ws_url: str | None = None
        self._user_agent = ""  # resolved from the override or the engine version in _bring_up
        self._browser_version = ""  # the engine version, for matching the client-hint brands
        self._task: asyncio.Task | None = None

    @property
    def available(self) -> bool:
        # Fail-closed: never report available unless the SSRF proxy is up, so a fetch is
        # never made without out-of-browser SSRF enforcement.
        return (
            self._browser is not None and self._browser.is_connected() and self._proxy_up
        )

    @property
    def cdp_url(self) -> str | None:
        """The container's CDP endpoint for another client to attach to, or None when
        there is nothing safe to attach to.

        Gated on :attr:`available` for the same fail-closed reason it is: handing out the
        endpoint while the SSRF proxy is down would let a second client reach the network
        unguarded, which is precisely what that flag exists to prevent.
        """
        return self._ws_url if self.available else None

    async def start(self) -> None:
        """Begin bring-up. Returns immediately — the pull/launch/connect runs in a
        background task so app startup is never blocked. A no-op when disabled."""
        if not self._enabled:
            logger.info("web fetch: browser disabled")
            return
        if self._task is not None:  # already bringing up
            return
        logger.info("web fetch: bringing up the browser container in the background")
        self._task = asyncio.create_task(self._bring_up())

    async def stop(self) -> None:
        """Cancel an in-flight bring-up, drop the CDP connection, and tear down the
        container. ``_bring_up`` logs its own failures, so the task only raises on the
        cancellation below."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self._disconnect()  # clears _proxy_up
        if self._runtime is not None:
            # Remove the proxy first — it shares the browser's network namespace.
            await force_remove_container(self._runtime, _PROXY_CONTAINER)
            await force_remove_container(self._runtime, _CONTAINER)

    @asynccontextmanager
    async def context(self, url: str | None = None) -> AsyncIterator[BrowserContext]:
        """A fresh, isolated, stealthed browser context for one fetch — concurrency-bounded
        and always closed. When a cookie jar is enabled and ``url`` is given, the site's
        cached cookies are seeded in (so a prior challenge's clearance carries forward) and
        the context's cookies are harvested back out on exit. Raises ``RuntimeError`` if the
        browser isn't available (the fetcher checks :attr:`available` first and degrades)."""
        async with self._sem:
            if not self.available:
                raise RuntimeError("browser is not available")
            assert self._browser is not None
            ctx = await self._browser.new_context(
                accept_downloads=False,
                service_workers="block",
                **context_options(
                    user_agent=self._user_agent,
                    locale=self._locale,
                    timezone_id=self._timezone_id,
                ),
            )
            try:
                await ctx.add_init_script(INIT_SCRIPT)
                if self._jar is not None and url:
                    seed = self._jar.seed_for(url)
                    if seed:
                        try:
                            await ctx.add_cookies(seed)
                        except Exception:
                            # add_cookies is all-or-nothing — one malformed entry would drop
                            # the whole seed (clearance cookie included). Re-add one at a
                            # time so a single bad cookie doesn't defeat the carry-forward.
                            for cookie in seed:
                                try:
                                    await ctx.add_cookies([cookie])
                                except Exception:
                                    pass
                yield ctx
            finally:
                if self._jar is not None:
                    try:
                        self._jar.store(await ctx.cookies())
                    except Exception:
                        pass  # context already gone ⇒ nothing to harvest
                try:
                    await ctx.close()
                except Exception:
                    pass

    async def apply_stealth(self, page) -> None:
        """Bring a page's client hints + ``navigator.userAgentData`` into agreement with
        the spoofed UA (and strip the headless shell's ``HeadlessChrome`` brand) via a CDP
        user-agent override. Must run before the page's first navigation. Best-effort: a
        CDP hiccup degrades to UA-string-only stealth rather than failing an otherwise-fine
        fetch — the JS-surface evasions (init script) are unaffected either way."""
        try:
            cdp = await page.context.new_cdp_session(page)
            await cdp.send(
                "Emulation.setUserAgentOverride",
                user_agent_override(
                    user_agent=self._user_agent,
                    locale=self._locale,
                    browser_version=self._browser_version,
                ),
            )
        except Exception:
            logger.debug("web fetch: client-hint override failed; UA-string stealth only")

    async def _bring_up(self) -> None:
        runtime = discover_runtime(self._runtime_pref)
        if runtime is None:
            logger.info("web fetch: no container runtime — web fetch unavailable")
            return
        self._runtime = runtime
        try:
            if not await ensure_image(runtime, self._image):
                logger.info("web fetch: no browser image available — web fetch unavailable")
                return
            await force_remove_container(runtime, _PROXY_CONTAINER)  # clear any stale pair
            await force_remove_container(runtime, _CONTAINER)
            _timed_out, code, _out, err = await run_subprocess(
                detached_run_argv(
                    runtime, _CONTAINER, self._flags(), self._image,
                    [*LAUNCH_FLAGS, *_PROXY_FLAGS],
                ),
                timeout_s=60.0,
            )
            if code != 0:
                logger.warning(
                    "web fetch: browser container failed to start: %s",
                    err.decode("utf-8", "replace").strip(),
                )
                await force_remove_container(runtime, _CONTAINER)
                return
            host_port = await published_host_port(runtime, _CONTAINER, _INTERNAL_PORT)
            await await_listening(host_port, self._startup_timeout_s)
            ws_url = await self._discover_ws(host_port)
        except SandboxError as exc:
            logger.warning("web fetch: browser did not come up: %s", exc)
            await force_remove_container(runtime, _CONTAINER)
            return
        except Exception:
            logger.exception("web fetch: browser bring-up failed unexpectedly")
            await force_remove_container(runtime, _CONTAINER)
            return
        try:
            pw = await async_playwright().start()
            self._pw = pw
            browser = await pw.chromium.connect_over_cdp(ws_url)
            self._browser = browser
            self._ws_url = ws_url
        except Exception:
            logger.exception("web fetch: could not connect to the browser over CDP")
            await self._disconnect()
            await force_remove_container(runtime, _CONTAINER)
            return
        self._browser_version = browser.version
        self._user_agent = self._user_agent_override or realistic_user_agent(browser.version)
        # The browser is up but points at a not-yet-listening proxy; bring the SSRF proxy up
        # now (it joins the browser's namespace). Until it is ready, available stays False.
        if not await self._start_proxy(runtime):
            logger.warning("web fetch: SSRF proxy did not come up — web fetch unavailable")
            await self._disconnect()
            await force_remove_container(runtime, _PROXY_CONTAINER)
            await force_remove_container(runtime, _CONTAINER)
            return
        self._proxy_up = True
        logger.info("web fetch: browser ready (Chromium %s) with SSRF proxy", browser.version)

    async def _start_proxy(self, runtime: str) -> bool:
        """Launch the SSRF proxy sidecar into the browser's network namespace and wait for
        it to report listening. Best-effort: any failure ⇒ False ⇒ web fetch stays down."""
        if not await ensure_image(runtime, self._proxy_image):
            logger.info("web fetch: no proxy image available")
            return False
        _timed_out, code, _out, err = await run_subprocess(
            detached_run_argv(
                runtime, _PROXY_CONTAINER, self._proxy_flags(), self._proxy_image,
                ["python", "/proxy.py", str(_PROXY_PORT)],
            ),
            timeout_s=60.0,
        )
        if code != 0:
            logger.warning(
                "web fetch: proxy container failed to start: %s",
                err.decode("utf-8", "replace").strip(),
            )
            return False
        return await self._await_proxy_ready(runtime)

    async def _await_proxy_ready(self, runtime: str) -> bool:
        """Poll the proxy's logs for its readiness line (it prints one when listening), then
        confirm the container is still running — a print-then-crash would otherwise leave the
        log line behind and mark a dead proxy ready (every fetch would then fail)."""
        for _ in range(int(self._startup_timeout_s / 0.25) + 1):
            _timed_out, _code, out, _err = await run_subprocess(
                [runtime, "logs", _PROXY_CONTAINER], timeout_s=5.0
            )
            if b"PROXY-READY" in out:
                _t, _c, state, _e = await run_subprocess(
                    [runtime, "inspect", "-f", "{{.State.Running}}", _PROXY_CONTAINER],
                    timeout_s=5.0,
                )
                return b"true" in state.lower()
            await asyncio.sleep(0.25)
        return False

    async def _discover_ws(self, host_port: int) -> str:
        """Read the CDP websocket endpoint from ``/json/version`` and rewrite its authority
        to our published loopback port (the container reports its own internal port)."""
        deadline_polls = int(self._startup_timeout_s / 0.25) + 1
        async with httpx.AsyncClient() as client:
            for _ in range(deadline_polls):
                try:
                    resp = await client.get(
                        f"http://127.0.0.1:{host_port}/json/version", timeout=2.0
                    )
                    if resp.status_code == 200:
                        raw = json.loads(resp.text)["webSocketDebuggerUrl"]
                        parts = urllib.parse.urlsplit(raw)
                        return urllib.parse.urlunsplit(
                            (parts.scheme, f"127.0.0.1:{host_port}", parts.path, "", "")
                        )
                except (httpx.HTTPError, KeyError, ValueError):
                    pass
                await asyncio.sleep(0.25)
        raise SandboxError("the browser's CDP endpoint did not become available")

    async def _disconnect(self) -> None:
        self._proxy_up = False
        self._ws_url = None
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._pw is not None:
            try:
                await self._pw.stop()
            except Exception:
                pass
            self._pw = None

    def _flags(self) -> list[str]:
        """Container isolation + the loopback-published CDP port. ``--network bridge`` so
        the browser can reach the open web; the proxy sidecar (sharing this namespace) gates
        every request it makes."""
        return [
            "--network", "bridge",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            # This container runs untrusted page JS: immutable root filesystem, with a
            # tmpfs for the only path Chromium needs to write (its temp/crashpad dir).
            "--read-only",
            "--tmpfs", "/tmp",
            "--memory", _MEMORY,
            "--shm-size", _SHM_SIZE,
            "--pids-limit", str(_PIDS_LIMIT),
            "--publish", f"127.0.0.1:0:{_INTERNAL_PORT}",
        ]

    def _proxy_flags(self) -> list[str]:
        """The proxy sidecar: joins the browser's network namespace (reached over loopback,
        no host networking), hardened like every other container, with the SSRF script
        mounted read-only into a stock python image."""
        return [
            "--network", f"container:{_CONTAINER}",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--read-only",
            "--tmpfs", "/tmp",
            "--memory", "256m",
            "--pids-limit", "256",
            "--env", "PYTHONDONTWRITEBYTECODE=1",
            "--env", "PYTHONUNBUFFERED=1",
            "--volume", f"{_PROXY_SCRIPT}:/proxy.py:ro",
        ]
