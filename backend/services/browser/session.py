"""The agent's controllable browser — one live page per conversation.

`pydantic_ai_harness.playwright` gives the model eighteen typed browser tools; what it
does *not* give is a browser that outlives a turn. `PlaywrightBrowser.wrap_run` opens the
session when a run starts and closes it when the run ends, which is right for a one-shot
agent and wrong for a chat thread: an operator who watches the agent log into a site and
then says "now open the billing page" is talking about *that* page. So the capability's
per-run lifecycle is bypassed here and the session is keyed by conversation instead,
reaped on idleness the way a sandbox session is (``services/sandbox/session.py`` is the
model this follows, down to the token tombstones).

**It attaches; it does not launch.** The session connects over CDP to the containerized
Chromium web fetch already runs (``services/webfetch/browser.py``), so page JavaScript
executes in that container rather than in this process, and every request the agent makes
goes out through the SSRF proxy sidecar that container is pointed at. One browser, one
proxy, one thing offline mode has to take down — and no Chromium binary on the host.

**The egress guard is deliberately left off.** ``EgressPolicy`` enforces its allowlist
with Playwright routing, which turns on CDP's Fetch domain; ``services/webfetch/browser``
documents why that is unacceptable here (bot walls detect it, and a page that trips one
renders as a challenge instead of content). Passing ``block_private_addresses=False``
with no allowlist leaves the policy unenforced, so no route is installed and the proxy —
which resolves each destination and refuses non-public addresses out of process — remains
the single enforcement point. The default is ``True``, so this must be explicit.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
import time
from typing import Any

from pydantic_ai_harness.playwright import EgressPolicy, PlaywrightBrowserSession

from services.webfetch import ManagedBrowser
from services.webfetch.stealth import INIT_SCRIPT

from .screencast import Screencast

logger = logging.getLogger(__name__)

#: How long a token stays a recognized "this session is gone" tombstone after its session
#: was reaped, before it is pruned as merely unknown. Long enough that an operator who
#: left the panel open across the idle window gets a legible answer rather than a bare
#: "no such session" when they come back to it.
_STOPPED_TOKEN_TTL_S = 3600.0


class ControlledBrowserSession(PlaywrightBrowserSession):
    """A harness browser session that never closes the browser it attached to.

    The base session owns its browser handle and closes it on exit, which is correct when
    it launched one. Ours is a CDP attachment to a container Chromium that web fetch is
    still using, so dropping the handle before teardown leaves the pages, the context and
    the driver to be cleaned up while the browser itself keeps running. Playwright's
    CDP-attached ``close()`` happens to only close the transport today; not relying on
    that is the point — this holds whether or not that stays true.
    """

    async def __aexit__(self, exc_type: type[BaseException] | None, *args: object) -> None:
        self._browser = None  # pyright: ignore[reportPrivateUsage]
        await super().__aexit__(exc_type, *args)


class LiveBrowser:
    """One conversation's browser: the harness session, plus the stream of what it shows."""

    def __init__(
        self,
        key: str,
        token: str,
        session: ControlledBrowserSession,
        screencast: Screencast,
    ) -> None:
        self.key = key
        self.token = token
        self.session = session
        self.screencast = screencast
        self._last_used = time.monotonic()

    def touch(self) -> None:
        self._last_used = time.monotonic()

    def idle_seconds(self, now: float) -> float:
        return now - self._last_used

    @property
    def page_url(self) -> str:
        page = self.session.page
        return getattr(page, "url", "") or "" if page is not None else ""

    async def teardown(self) -> None:
        """Close this session, waking every watcher first. Never raises."""
        self.screencast.close()
        with contextlib.suppress(Exception):
            await self.screencast.stop()
        with contextlib.suppress(Exception):
            await self.session.__aexit__(None, None, None)


class BrowserSessionManager:
    """Maps a conversation to its live browser, reaping idle ones.

    Degrades rather than fails: when the managed browser is unavailable — no container
    runtime, a failed pull, the SSRF proxy down, or offline mode having suspended it —
    :meth:`acquire` returns ``None`` and the browse tools tell the model so, exactly as
    web fetch degrades under the same conditions.
    """

    def __init__(
        self,
        managed: ManagedBrowser,
        *,
        idle_ttl_s: float,
        reap_interval_s: float,
        max_live: int,
        frame_width: int = 1280,
        frame_height: int = 800,
        frame_quality: int = 60,
    ) -> None:
        self._managed = managed
        self._idle_ttl = idle_ttl_s
        self._reap_interval = reap_interval_s
        self._max_live = max(1, max_live)
        self._frame_width = frame_width
        self._frame_height = frame_height
        self._frame_quality = frame_quality
        self._sessions: dict[str, LiveBrowser] = {}
        # token → conversation key, so the stream route resolves a session in O(1).
        self._tokens: dict[str, str] = {}
        # token → monotonic time its session was torn down, so a panel whose socket
        # dropped can be told "reaped" rather than "unknown" (see `_STOPPED_TOKEN_TTL_S`).
        self._stopped_tokens: dict[str, float] = {}
        self._lock = asyncio.Lock()
        # Per-conversation creation locks. Tool calls within one model response run
        # concurrently, so two browse tools can race the first acquire of a thread; without
        # this they would each attach a session and one would be silently orphaned.
        self._creating: dict[str, asyncio.Lock] = {}
        self._reaper: asyncio.Task[None] | None = None

    # ── lookup ───────────────────────────────────────────────────────────────────

    def existing(self, key: str) -> LiveBrowser | None:
        """This conversation's browser if it already has one, **without** starting it —
        so a turn that never browsed pays nothing."""
        return self._sessions.get(key)

    def resolve(self, token: str) -> LiveBrowser | None:
        """The session a stream request names, or None. Touches it, so an operator
        watching the panel keeps the browser alive. Sync, so it reads the maps atomically
        against the reaper."""
        key = self._tokens.get(token)
        live = self._sessions.get(key) if key is not None else None
        if live is None or live.token != token:
            return None
        live.touch()
        return live

    def status(self, token: str) -> str:
        """``"live"``, ``"stopped"`` (reaped or evicted), or ``"unknown"``.

        Read-only — unlike :meth:`resolve`, asking after a session must not itself keep an
        otherwise-idle browser warm.
        """
        key = self._tokens.get(token)
        live = self._sessions.get(key) if key is not None else None
        if live is not None and live.token == token:
            return "live"
        return "stopped" if token in self._stopped_tokens else "unknown"

    # ── lifecycle ────────────────────────────────────────────────────────────────

    async def acquire(self, key: str) -> LiveBrowser | None:
        """This conversation's browser, attaching one on first use.

        Returns ``None`` when there is no browser to attach to, which is a degraded
        capability rather than an error: the caller reports it to the model.
        """
        live = self._sessions.get(key)
        if live is not None:
            live.touch()
            return live
        lock = self._creating.setdefault(key, asyncio.Lock())
        async with lock:
            live = self._sessions.get(key)
            if live is not None:
                live.touch()
                return live
            live = await self._attach(key)
            if live is None:
                return None
            async with self._lock:
                self._sessions[key] = live
                self._tokens[live.token] = key
            await self._enforce_cap()
            return live

    async def _attach(self, key: str) -> LiveBrowser | None:
        cdp_url = self._managed.cdp_url
        if cdp_url is None:
            return None
        session = ControlledBrowserSession(
            # Unenforced by design — the proxy sidecar is the egress boundary. See the
            # module docstring; the default is True, so this must be said out loud.
            policy=EgressPolicy(block_private_addresses=False),
            cdp_url=cdp_url,
        )
        await session.__aenter__()
        try:
            page = await session.ensure_page()
            await self._prepare(page)
        except Exception:
            logger.warning("browser: could not open a page for %s", key, exc_info=True)
            with contextlib.suppress(Exception):
                await session.__aexit__(None, None, None)
            return None
        screencast = Screencast(
            session,
            max_width=self._frame_width,
            max_height=self._frame_height,
            quality=self._frame_quality,
        )
        return LiveBrowser(key, secrets.token_urlsafe(32), session, screencast)

    async def _prepare(self, page: Any) -> None:
        """Bring a freshly-attached page up to the same disguise every fetched page gets.

        The harness builds its own browser context and exposes no seam for context
        options, so the three things ``ManagedBrowser.context`` sets at construction are
        applied to the page afterwards instead — all through public API, none of it
        reaching into the harness's private launch path. Best-effort, individually: a page
        that browses without the client-hint override is worse at passing for a real
        browser, not broken.
        """
        with contextlib.suppress(Exception):
            await self._managed.apply_stealth(page)
        with contextlib.suppress(Exception):
            await page.add_init_script(INIT_SCRIPT)
        with contextlib.suppress(Exception):
            # A CDP-attached context has no default viewport, so pages come up at the
            # container's own small size; this is the viewport `stealth.context_options`
            # would have given a launched context.
            cdp = await page.context.new_cdp_session(page)
            await cdp.send(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": self._frame_width,
                    "height": self._frame_height,
                    "deviceScaleFactor": 1,
                    "mobile": False,
                },
            )
            await cdp.detach()

    async def release(self, key: str) -> None:
        """Tear down one conversation's browser. Idempotent."""
        async with self._lock:
            live = self._sessions.pop(key, None)
            if live is not None:
                self._tombstone(live)
        if live is not None:
            await live.teardown()

    async def _enforce_cap(self) -> None:
        """Evict least-recently-used sessions past the cap.

        Each live session holds a Playwright driver subprocess of its own, so this is a
        real resource ceiling rather than tidiness. An evicted conversation's panel learns
        about it on its own socket, which closes with the session.
        """
        async with self._lock:
            if len(self._sessions) <= self._max_live:
                return
            now = time.monotonic()
            ordered = sorted(
                self._sessions.values(),
                key=lambda live: live.idle_seconds(now),
                reverse=True,
            )
            evicted = ordered[: len(self._sessions) - self._max_live]
            for live in evicted:
                self._sessions.pop(live.key, None)
                self._tombstone(live)
        for live in evicted:
            logger.info("browser: evicted the session for %s (over the live cap)", live.key)
            await live.teardown()

    def _prune_creation_locks(self) -> None:
        """Drop creation locks for conversations that hold no session and have nobody
        mid-acquire. Every other map here is bounded or reaped; without this one pass the
        locks would be the one structure that only ever grew, an entry per conversation
        that ever browsed, for the life of the process.

        Safe against a concurrent :meth:`acquire`: `setdefault` and an uncontended
        `Lock.acquire()` both complete without suspending, so no caller can be observed
        between choosing its lock and holding it. A key dropped while unlocked simply gets
        a fresh lock on the next acquire.
        """
        self._creating = {
            key: lock
            for key, lock in self._creating.items()
            if lock.locked() or key in self._sessions
        }

    def _tombstone(self, live: LiveBrowser) -> None:
        """Record a torn-down session's token as stopped, and prune stale records.
        Called under the lock, before the session is actually torn down."""
        now = time.monotonic()
        cutoff = now - _STOPPED_TOKEN_TTL_S
        self._stopped_tokens = {t: ts for t, ts in self._stopped_tokens.items() if ts > cutoff}
        self._stopped_tokens[live.token] = now
        self._tokens.pop(live.token, None)

    async def start(self) -> None:
        self._reaper = asyncio.create_task(self._reaper_loop())

    async def stop(self) -> None:
        reaper, self._reaper = self._reaper, None
        if reaper is not None:
            reaper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reaper
        async with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
            self._tokens.clear()
        for live in sessions:
            await live.teardown()

    async def _reaper_loop(self) -> None:
        while True:
            await asyncio.sleep(self._reap_interval)
            try:
                await self._sweep()
            except Exception:  # noqa: BLE001 — the reaper must survive a bad sweep
                logger.debug("browser: sweep failed", exc_info=True)

    async def _sweep(self) -> None:
        """Reap idle sessions — and every session at once when the browser itself is gone.

        The second case is how offline mode reaches this manager without knowing it
        exists: suspending web fetch stops the container, ``cdp_url`` goes ``None``, and
        the next sweep clears the sessions attached to a browser that is no longer there.
        """
        gone = self._managed.cdp_url is None
        now = time.monotonic()
        async with self._lock:
            stale = [
                live
                for live in self._sessions.values()
                if gone or live.idle_seconds(now) >= self._idle_ttl
            ]
            for live in stale:
                self._sessions.pop(live.key, None)
                self._tombstone(live)
            self._prune_creation_locks()
        for live in stale:
            logger.info(
                "browser: reaped the session for %s (%s)",
                live.key,
                "browser unavailable" if gone else "idle",
            )
            await live.teardown()
