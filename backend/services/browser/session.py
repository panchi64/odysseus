"""The agent's controllable browser — one live page per conversation, in a real window.

`pydantic_ai_harness.playwright` gives the model eighteen typed browser tools; what it
does *not* give is a browser that outlives a turn. `PlaywrightBrowser.wrap_run` opens the
session when a run starts and closes it when the run ends, which is right for a one-shot
agent and wrong for a chat thread: an operator who watches the agent log into a site and
then says "now open the billing page" is talking about *that* page. So the capability's
per-run lifecycle is bypassed here and the session is keyed by conversation instead,
reaped on idleness the way a sandbox session is (``services/sandbox/manager.py`` is the
model this follows, down to the token tombstones).

**It attaches to the window we launched, and the operator shares it.** ``HostBrowser``
owns one visible Chromium on the operator's machine; each conversation gets its own
browser *context* on it, which in a headed Chromium is its own window with its own cookie
jar. The operator can click in that window — to log in before handing the thread over, or
to do one step faster than describing it — and the agent re-reads the page afterwards
like any other change. Nothing arbitrates between the two drivers, deliberately.

**The egress guard is deliberately left off.** ``EgressPolicy`` enforces its allowlist
with Playwright routing, which turns on CDP's Fetch domain; ``services/webfetch/browser``
documents why that is unacceptable here (bot walls detect it, and a page that trips one
renders as a challenge instead of content). Passing ``block_private_addresses=False``
with no allowlist leaves the policy unenforced, so no route is installed and the proxy
``HostBrowser`` points the window at — which resolves each destination and refuses
non-public addresses out of process — remains the single enforcement point. The default
is ``True``, so this must be explicit.

A conversation's login survives its session, saved and restored around the attach — see
``services/browser/live.py``, which owns one session and everything that outlives it.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import secrets
import time
from pathlib import Path
from typing import Any

from pydantic_ai_harness.playwright import EgressPolicy

from .host import HostBrowser
from .live import ControlledBrowserSession, LiveBrowser

logger = logging.getLogger(__name__)

#: Anything that is not plainly filename-safe in a conversation id. Ids are generated, not
#: typed, so this is containment rather than sanitation — but a key also stands in for a
#: run id on a stateless turn, and a state file must never be able to name a path.
_UNSAFE = re.compile(r"[^A-Za-z0-9_-]+")


class BrowserSessionManager:
    """Maps a conversation to its live browser, reaping idle ones.

    Degrades rather than fails: when no window can be opened — Chromium missing, the SSRF
    proxy refusing to start, the operator having quit the browser mid-launch —
    :meth:`acquire` returns ``None`` and the browse tools tell the model so, exactly as
    web fetch degrades under the same conditions.
    """

    def __init__(
        self,
        host: HostBrowser,
        *,
        idle_ttl_s: float,
        reap_interval_s: float,
        max_live: int,
        state_dir: Path | None = None,
    ) -> None:
        self._host = host
        self._idle_ttl = idle_ttl_s
        self._reap_interval = reap_interval_s
        self._max_live = max(1, max_live)
        self._state_dir = state_dir
        self._sessions: dict[str, LiveBrowser] = {}
        self._lock = asyncio.Lock()
        # Per-conversation creation locks. Tool calls within one model response run
        # concurrently, so two browse tools can race the first acquire of a thread; without
        # this they would each attach a session and one would be silently orphaned.
        self._creating: dict[str, asyncio.Lock] = {}
        # Conversations whose window the *operator* closed. Not a cache and not an error
        # state — a record of a decision somebody made, kept so the next tool call reports
        # it instead of quietly launching a replacement window on their screen. Cleared
        # the moment a session attaches again, which only something explicit can cause.
        self._closed: set[str] = set()
        self._reaper: asyncio.Task[None] | None = None

    # ── lookup ───────────────────────────────────────────────────────────────────

    def existing(self, key: str) -> LiveBrowser | None:
        """This conversation's browser if it already has one, **without** starting it —
        so a turn that never browsed pays nothing."""
        return self._sessions.get(key)

    def closed(self, key: str) -> bool:
        """Whether this conversation's window was closed by the operator rather than by us.

        The distinction the caller needs in order to say something true. A session that was
        reaped for idleness is *ours* to re-attach silently — the login is restored and the
        model never needed to know. A window the operator closed is a thing they did, and
        the honest report is that they did it.
        """
        return key in self._closed

    # ── lifecycle ────────────────────────────────────────────────────────────────

    async def acquire(
        self, key: str, *, focus: bool = False, reopen: bool = True
    ) -> LiveBrowser | None:
        """This conversation's browser, launching and attaching one on first use.

        Returns ``None`` when no browser could be opened, which is a degraded capability
        rather than an error: the caller reports it to the model.

        ``focus`` is for the operator's own "open the browser" control, where the window
        appearing behind the app would look like nothing happened. The agent never sets
        it: a tool call stealing focus mid-sentence is the panel-that-pops-up problem in
        a more disruptive form.

        ``reopen`` is what a caller says when it is *allowed* to put a new window on the
        operator's screen. It defaults to True because the operator's own control is a
        caller too; the browse tools pass False for everything except an explicit
        ``navigate`` (:data:`tools.browse.REOPENING_TOOLS`). Closing the window is how
        somebody says they are done with it, and a tool call that silently launched a
        replacement would overrule that — while still, from the model's side, behaving as
        if the page it was working on had simply gone blank.
        """
        live = self._sessions.get(key)
        if live is not None and (self._host.cdp_url is None or live.abandoned):
            # The window this session was attached to is gone. Only the sweep looks for
            # that, and it runs on its own clock, so without this an operator who quits
            # Chromium and immediately reopens their browser gets a cheerful "open" on a
            # dead session — and the agent gets raw Playwright errors instead of the
            # degrade. Drop it here, and remember *who* ended it.
            await self.release(key)
            self._closed.add(key)
            live = None
        if live is None and key in self._closed and not reopen:
            return None
        if live is None:
            lock = self._creating.setdefault(key, asyncio.Lock())
            async with lock:
                live = self._sessions.get(key)
                if live is None:
                    live = await self._attach(key)
                    if live is None:
                        return None
                    # A window is open again, so whatever was closed before is history.
                    self._closed.discard(key)
                    async with self._lock:
                        self._sessions[key] = live
                    await self._enforce_cap()
        live.touch()
        if focus:
            await self._bring_to_front(live)
        return live

    async def _attach(self, key: str) -> LiveBrowser | None:
        cdp_url = await self._host.ensure()
        if cdp_url is None:
            return None
        session = ControlledBrowserSession(
            # Unenforced by design — the proxy is the egress boundary. See the module
            # docstring; the default is True, so this must be said out loud.
            policy=EgressPolicy(block_private_addresses=False),
            cdp_url=cdp_url,
            storage_state=self._load_state(key),
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
        return LiveBrowser(
            key,
            secrets.token_urlsafe(32),
            session,
            self._state_path(key),
            # The window itself, so the session can tell an operator's own tabs from the
            # ones the harness happens to track. See `live.LiveBrowser.open_pages`.
            getattr(page, "context", None),
        )

    async def _prepare(self, page: Any) -> None:
        """Bring a freshly-attached page up to the same disguise every fetched page gets.

        Best-effort: a page that browses without the automation masking is worse at passing
        for a real browser, not broken. Nothing here raises the window — the attach happens
        on the agent's first browse tool call as often as on the operator's own action, and
        only the latter asked for a window in front of them.
        """
        with contextlib.suppress(Exception):
            await self._host.apply_stealth(page)

    async def _bring_to_front(self, live: LiveBrowser) -> None:
        page = live.session.page
        if page is None:
            return
        with contextlib.suppress(Exception):
            await page.bring_to_front()

    def _state_path(self, key: str) -> Path | None:
        """Where this conversation's cookies live, or ``None`` when nothing was
        configured (tests, mostly) and logins are simply not persisted."""
        if self._state_dir is None:
            return None
        return self._state_dir / f"{_UNSAFE.sub('-', key)}.json"

    def _load_state(self, key: str) -> Any | None:
        """The login this conversation had last time, if any. A missing file is the
        ordinary case (a first attach); an unreadable one is treated the same way, because
        starting logged out is a recoverable annoyance and refusing to attach is not."""
        path = self._state_path(key)
        if path is None or not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except Exception:
            logger.debug("browser: could not read the saved login for %s", key, exc_info=True)
            return None

    async def release(self, key: str) -> None:
        """Tear down one conversation's browser. Idempotent."""
        async with self._lock:
            live = self._sessions.pop(key, None)
        if live is not None:
            await live.teardown()

    async def purge(self, key: str) -> None:
        """Tear this conversation's browser down **and** delete the login it left behind.

        For a deleted conversation, where :meth:`release` alone would be worse than doing
        nothing: teardown writes the cookie jar out, so the sites this thread logged into
        would stay logged in on disk forever, keyed to a thread the operator destroyed. The
        state file is the most sensitive thing a conversation leaves anywhere — it *is* the
        sessions — so it goes with the workspace, the plan and the history. Idempotent.
        """
        await self.release(key)
        # ...including the note that its window was closed. The conversation is gone, so
        # there is nobody left for that to be true about, and this is the one map keyed by
        # conversation with no other reaper — every other entry it can hold belongs to a
        # thread that still exists and can still reopen.
        self._closed.discard(key)
        path = self._state_path(key)
        if path is not None:
            with contextlib.suppress(OSError):
                path.unlink(missing_ok=True)

    async def _enforce_cap(self) -> None:
        """Evict least-recently-used sessions past the cap.

        Each live session holds a Playwright driver subprocess and a window of its own, so
        this is a real resource ceiling rather than tidiness — and the operator's screen is
        part of the resource.
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
        """Reap what nobody is using — and every session at once when the window is gone.

        Three ways a session ends here, and they do not all mean the same thing. The
        operator quit Chromium (or its proxy died), so ``cdp_url`` is ``None`` and nothing
        any session holds is still real. They closed a conversation's last tab, which is as
        clear a "done with this" as there is. Or it simply sat unused — and *unused* counts
        the operator's own clicking, not only the agent's tool calls, or a browser being
        worked in by hand would be reaped out from under the person working in it.

        **The first two are theirs and the third is ours**, so only the first two leave a
        tombstone (:meth:`closed`). An idle reap is bookkeeping the model never needed to
        hear about: the next tool call re-attaches, the saved login comes back with it, and
        the only thing lost is where the page was pointed. A window somebody closed is a
        decision, and the next tool call says so instead of reopening one.
        """
        gone = self._host.cdp_url is None
        now = time.monotonic()
        reasons: list[tuple[LiveBrowser, str]] = []
        async with self._lock:
            for live in list(self._sessions.values()):
                if gone:
                    reasons.append((live, "browser unavailable"))
                elif live.abandoned:
                    reasons.append((live, "closed"))
                elif live.moved_since_last_sweep():
                    live.touch()
                elif live.idle_seconds(now) >= self._idle_ttl:
                    reasons.append((live, "idle"))
            for live, reason in reasons:
                self._sessions.pop(live.key, None)
                if reason != "idle":
                    self._closed.add(live.key)
            self._prune_creation_locks()
        for live, reason in reasons:
            logger.info("browser: reaped the session for %s (%s)", live.key, reason)
            await live.teardown()
        if gone:
            # A quit window leaves its driver and its SSRF proxy running until something
            # asks for a browser again; if nothing ever does, the proxy would outlive the
            # window it guarded for the rest of the process. Only a still-dead host is
            # closed — a launch that happened between the check above and here survives.
            await self._host.close_if_dead()
