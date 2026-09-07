"""One conversation's browser: the attached session, and the login it leaves behind.

Split from the manager because these two answer different questions. The manager decides
*which* conversations hold a browser and for how long; this decides what one session is —
how it attaches without owning the window, how it can tell somebody is using it, and what
of it survives being torn down.

**Logins outlive the session on purpose.** A conversation's cookies and local storage are
written out when its session ends and read back when it next attaches. Without that, the
idle reap would quietly throw away the login the operator had just set up by hand — the
one thing this browser exists to make possible. The file is operator data on the
operator's disk, the same class as the sandbox workspace it sits beside.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from pydantic_ai_harness.playwright import PlaywrightBrowserSession

logger = logging.getLogger(__name__)


class ControlledBrowserSession(PlaywrightBrowserSession):
    """A harness browser session that never closes the browser it attached to.

    The base session owns its browser handle and closes it on exit, which is correct when
    it launched one. Ours is a CDP attachment to a window other conversations — and the
    operator — are still using, so dropping the handle before teardown leaves the pages,
    the context and the driver to be cleaned up while the browser itself keeps running.
    Playwright's CDP-attached ``close()`` happens to only close the transport today; not
    relying on that is the point — this holds whether or not that stays true.
    """

    async def __aexit__(self, exc_type: type[BaseException] | None, *args: object) -> None:
        self._browser = None  # pyright: ignore[reportPrivateUsage]
        await super().__aexit__(exc_type, *args)


class LiveBrowser:
    """One conversation's browser: the harness session and where its login is kept."""

    def __init__(
        self,
        key: str,
        token: str,
        session: ControlledBrowserSession,
        state_path: Path | None = None,
        context: Any | None = None,
    ) -> None:
        self.key = key
        self.token = token
        self.session = session
        self.state_path = state_path
        # The browser context the session attached to — the window itself, rather than the
        # harness's view of it. See `open_pages`.
        self.context = context
        self._last_used = time.monotonic()
        # What the last sweep saw, so the next one can tell "nobody touched this" from
        # "the operator has been working in it" — see `moved_since_last_sweep`.
        self._events_seen = getattr(session, "events_recorded", 0)
        self._urls_seen = self._open_urls()

    def touch(self) -> None:
        self._last_used = time.monotonic()

    def idle_seconds(self, now: float) -> float:
        return now - self._last_used

    @property
    def page_url(self) -> str:
        page = self.session.page
        return getattr(page, "url", "") or "" if page is not None else ""

    @property
    def open_pages(self) -> list[Any]:
        """Every tab really open in this conversation's window.

        Asked of the browser context rather than of ``session.pages``, which holds only the
        tabs the harness wired: the one it opened plus popups a page spawned. A tab the
        operator opened themselves is in neither, and judging the window by that list would
        call a window they are working in empty — then close it under them, since tearing
        the session down drops the CDP client the whole context belongs to. The tracked
        list is the fallback for a session that never handed one over.
        """
        context = self.context
        if context is not None:
            try:
                return list(context.pages)
            except Exception:  # noqa: BLE001 — a context whose browser is gone answers here
                return []
        return list(getattr(self.session, "pages", []))

    @property
    def abandoned(self) -> bool:
        """True once the window has no tabs left — the operator closed the last one, and
        there is nothing for this session to be *about* any more."""
        return not self.open_pages

    def moved_since_last_sweep(self) -> bool:
        """Whether anything happened here since the previous sweep asked.

        The idle clock is only touched by the agent's own tool calls, so an operator
        reading, clicking and typing in the window all afternoon would look perfectly idle
        and be reaped mid-login. The harness counts every browser event it records, and the
        address bars move on navigations it never sees — every tab's, not just the agent's,
        or working in a tab of one's own would still read as idle. Either changing is
        somebody using this browser. Stateful by necessity — it consumes what it observed,
        so only the sweep may call it.
        """
        events = getattr(self.session, "events_recorded", self._events_seen)
        urls = self._open_urls()
        moved = events != self._events_seen or urls != self._urls_seen
        self._events_seen, self._urls_seen = events, urls
        return moved

    def _open_urls(self) -> tuple[str, ...]:
        return tuple(getattr(page, "url", "") or "" for page in self.open_pages)

    async def teardown(self) -> None:
        """Save this conversation's login, then close the session. Never raises."""
        await self._save_state()
        with contextlib.suppress(Exception):
            await self.session.__aexit__(None, None, None)

    async def _save_state(self) -> None:
        """Write the context's cookies and local storage where the next attach will find
        them. Best-effort: a window the operator already quit has no state left to read,
        and losing a login is worth strictly less than a teardown that completes."""
        page = self.session.page
        context = self.context if self.context is not None else getattr(page, "context", None)
        if self.state_path is None or context is None:
            return
        try:
            state = await context.storage_state()
            write_state(self.state_path, state)
        except Exception:
            logger.debug("browser: could not save the login state for %s", self.key, exc_info=True)


def write_state(path: Path, state: Any) -> None:
    """Write a storage state atomically, owner-only.

    Atomic because a torn write is worse than no file at all: the next attach would read
    half a cookie jar and fail rather than simply starting logged out. Owner-only because
    these *are* the sessions — anything that can read the file is logged into whatever the
    operator logged into.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(state, handle)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
