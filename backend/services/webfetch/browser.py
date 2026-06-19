"""ManagedBrowser — the headless Chromium the web fetcher renders pages in, isolated in
a container.

Rendering a page means executing its untrusted JavaScript, so the browser must not run in
the backend process. It runs in its own loopback-bound container (the Docker/Podman
runtime the sandbox and managed SearXNG already use) and we drive it over the Chrome
DevTools Protocol via Playwright ``connect_over_cdp``. Two payoffs over an in-process
browser: untrusted page JS is isolated from the host, and the container's separate network
namespace means even an SSRF-guard bypass (e.g. a timed DNS rebind) cannot reach the host's
own loopback services. CDP is version-tolerant, so the image tracks ``:latest`` (refreshed
each boot by :func:`ensure_image`) without being pinned to the Python client's Playwright
version.

Bring-up is **best-effort and non-fatal** (mirrors :class:`services.searxng.ManagedSearxng`):
no container runtime, a failed pull, or a browser that never binds leaves :attr:`available`
False and web fetch degrades — it never blocks app startup. The work runs in a background
task so the app boots immediately. Each fetch gets a fresh, stealthed, ephemeral context
(no shared cookies/storage); total concurrency is bounded.
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.parse
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

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

from .stealth import INIT_SCRIPT, context_options, realistic_user_agent

logger = logging.getLogger(__name__)

# The one container we name, the CDP port it exposes inside it, and conservative caps —
# a browser is heavier than SearXNG, and Chromium crashes on a tiny /dev/shm.
_CONTAINER = "odysseus-webfetch"
_INTERNAL_PORT = 9222
_MEMORY = "2g"
_SHM_SIZE = "1g"
_PIDS_LIMIT = 1024


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
        runtime_pref: str | None = None,
    ) -> None:
        self._enabled = enabled
        self._image = image
        self._startup_timeout_s = startup_timeout_s
        self._sem = asyncio.Semaphore(max(1, concurrency))
        self._user_agent_override = user_agent
        self._locale = locale
        self._timezone_id = timezone_id
        self._runtime_pref = runtime_pref
        self._runtime: str | None = None
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._user_agent = ""  # resolved from the override or the engine version in _bring_up
        self._task: asyncio.Task | None = None

    @property
    def available(self) -> bool:
        return self._browser is not None and self._browser.is_connected()

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
        await self._disconnect()
        if self._runtime is not None:
            await force_remove_container(self._runtime, _CONTAINER)

    @asynccontextmanager
    async def context(self) -> AsyncIterator[BrowserContext]:
        """A fresh, isolated, stealthed browser context for one fetch — concurrency-bounded
        and always closed. Raises ``RuntimeError`` if the browser isn't available (the
        fetcher checks :attr:`available` first and degrades before calling this)."""
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
                yield ctx
            finally:
                try:
                    await ctx.close()
                except Exception:
                    pass

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
            await force_remove_container(runtime, _CONTAINER)  # clear any stale one
            _timed_out, code, _out, err = await run_subprocess(
                detached_run_argv(runtime, _CONTAINER, self._flags(), self._image, []),
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
        except Exception:
            logger.exception("web fetch: could not connect to the browser over CDP")
            await self._disconnect()
            await force_remove_container(runtime, _CONTAINER)
            return
        self._user_agent = self._user_agent_override or realistic_user_agent(browser.version)
        logger.info("web fetch: browser ready (Chromium %s)", browser.version)

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
        the browser can reach the open web; the SSRF guard gates every request it makes."""
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
