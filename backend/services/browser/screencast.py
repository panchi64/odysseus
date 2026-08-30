"""The live view of the agent's browser — a CDP screencast, fanned out to watchers.

Chromium will stream the rendered page as JPEG frames over the DevTools Protocol
(``Page.startScreencast``), which is how the operator watches the agent browse rather
than reading a transcript of clicks after the fact. Three things shape this module:

**Flow control is the ack.** Chromium withholds the next frame until the current one is
acknowledged (``Page.screencastFrameAck``), so acking *after* the fan-out — never before,
never on a timer — is the entire backpressure story. A slow watcher slows the stream
instead of growing an unbounded queue in this process.

**Watchers get the newest frame, not every frame.** Each subscriber holds a one-slot
queue; a frame arriving while the previous one is still unread replaces it. A stream of
screenshots has no history worth preserving — the operator wants to see *now*, and a
queue that buffered would only make them watch the past at a delay.

**The active tab moves underneath us.** ``tabs('select')``, a popup, or a closed tab all
swap ``session.page``, and the harness toolset exposes no hook to hear about it. A short
watchdog notices the swap and re-attaches the screencast to the new page; the same tick
refreshes the URL and title, which would otherwise cost a driver round-trip per frame.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

#: How often to check whether the active tab (or the page's URL/title) changed. Fast
#: enough that a click-through to a new tab doesn't visibly strand the panel on the old
#: one, slow enough to be nothing next to the frame stream it rides alongside.
_WATCHDOG_INTERVAL_S = 0.25


@dataclass(frozen=True)
class Frame:
    """One rendered frame plus the chrome the panel draws around it.

    The metadata rides on every frame rather than in a separate message so a watcher that
    joins mid-stream is immediately correct — there is no "first frame is special" case,
    and no window in which the panel shows a new page under the old page's URL.
    """

    data: str  # base64 JPEG, exactly as Chromium hands it over
    width: int
    height: int
    url: str
    title: str
    tabs: int
    active: int

    def envelope(self) -> dict[str, Any]:
        return {
            "t": "frame",
            "data": self.data,
            "w": self.width,
            "h": self.height,
            "url": self.url,
            "title": self.title,
            "tabs": self.tabs,
            "active": self.active,
        }


class Screencast:
    """A CDP screencast of a browser session's active page, fanned out to subscribers.

    Streaming only runs while somebody is watching: the first subscriber starts it and
    the last one to leave stops it, so a session the operator never opens the panel on
    costs no frames, no encoding, and no watchdog.
    """

    def __init__(
        self,
        session: Any,
        *,
        max_width: int = 1280,
        max_height: int = 800,
        quality: int = 60,
    ) -> None:
        self._session = session
        self._max_width = max_width
        self._max_height = max_height
        self._quality = quality
        self._subscribers: set[asyncio.Queue[Frame | None]] = set()
        self._cdp: Any = None
        self._page: Any = None
        self._watchdog: asyncio.Task[None] | None = None
        # In-flight acks. The loop holds only a weak reference to a task, so one that is
        # merely created and forgotten can be collected mid-send — and a dropped ack does
        # not surface as an error, it silently freezes the stream (Chromium withholds the
        # next frame until the current one is acknowledged). `PlaywrightBrowserSession`
        # keeps its own event tasks alive the same way, for the same reason.
        self._acks: set[asyncio.Task[None]] = set()
        self._url = ""
        self._title = ""
        self._lock = asyncio.Lock()

    # ── watchers ─────────────────────────────────────────────────────────────────

    def subscribe(self) -> asyncio.Queue[Frame | None]:
        """A one-slot queue of frames. ``None`` is the end-of-stream sentinel."""
        queue: asyncio.Queue[Frame | None] = asyncio.Queue(maxsize=1)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[Frame | None]) -> None:
        self._subscribers.discard(queue)

    @property
    def watchers(self) -> int:
        return len(self._subscribers)

    def close(self) -> None:
        """Wake every watcher with the end sentinel so their sockets close cleanly.

        Synchronous on purpose: it is called from teardown paths that are already
        unwinding, and dropping a sentinel into a bounded queue never blocks.
        """
        for queue in list(self._subscribers):
            _replace(queue, None)
        self._subscribers.clear()

    # ── lifecycle ────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Attach to the active page and begin streaming. Idempotent.

        The watchdog is keyed off its own field rather than off `_cdp`: an attach that
        fails (a page mid-navigation, a browser that just went) leaves `_cdp` unset but is
        retried by the watchdog itself, so a second caller must not start a *second* one.
        Two would fight over the same page, each detaching what the other attached, and
        `stop()` could only ever cancel the one it could see.
        """
        async with self._lock:
            if self._cdp is None:
                page = getattr(self._session, "page", None)
                if page is None:
                    return
                await self._attach(page)
            if self._watchdog is None:
                self._watchdog = asyncio.create_task(self._watch())

    async def stop(self) -> None:
        """Stop streaming and detach. Idempotent; safe on a browser that already died."""
        async with self._lock:
            watchdog, self._watchdog = self._watchdog, None
            if watchdog is not None:
                watchdog.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await watchdog
            await self._detach()

    async def _attach(self, page: Any) -> None:
        try:
            cdp = await page.context.new_cdp_session(page)
            cdp.on("Page.screencastFrame", self._on_frame)
            await cdp.send("Page.enable")
            await cdp.send(
                "Page.startScreencast",
                {
                    "format": "jpeg",
                    "quality": self._quality,
                    "maxWidth": self._max_width,
                    "maxHeight": self._max_height,
                    "everyNthFrame": 1,
                },
            )
        except Exception:  # noqa: BLE001 — a page that died mid-attach is not an error
            logger.debug("browser: could not start the screencast", exc_info=True)
            return
        self._cdp = cdp
        self._page = page
        self._url = _page_url(page)
        self._title = ""

    async def _detach(self) -> None:
        cdp, self._cdp, self._page = self._cdp, None, None
        if cdp is None:
            return
        try:
            await cdp.send("Page.stopScreencast")
            await cdp.detach()
        except Exception:  # noqa: BLE001 — teardown is best-effort by construction
            logger.debug("browser: screencast detach failed", exc_info=True)

    # ── frames ───────────────────────────────────────────────────────────────────

    def _on_frame(self, event: dict[str, Any]) -> None:
        """Chromium's frame callback. Sync (Playwright dispatches events synchronously),
        so the ack — which is a round-trip — is handed to a task."""
        metadata = event.get("metadata") or {}
        frame = Frame(
            data=event.get("data", ""),
            width=int(metadata.get("deviceWidth") or self._max_width),
            height=int(metadata.get("deviceHeight") or self._max_height),
            url=self._url,
            title=self._title,
            tabs=len(getattr(self._session, "pages", ()) or ()),
            active=self._active_index(),
        )
        for queue in list(self._subscribers):
            _replace(queue, frame)
        session_id = event.get("sessionId")
        if session_id is not None:
            task = asyncio.create_task(self._ack(session_id))
            self._acks.add(task)
            task.add_done_callback(self._acks.discard)

    async def _ack(self, session_id: int) -> None:
        cdp = self._cdp
        if cdp is None:
            return
        try:
            await cdp.send("Page.screencastFrameAck", {"sessionId": session_id})
        except Exception:  # noqa: BLE001 — a closed page stops the stream on its own
            logger.debug("browser: screencast ack failed", exc_info=True)

    def _active_index(self) -> int:
        pages = list(getattr(self._session, "pages", ()) or ())
        page = self._page
        for index, candidate in enumerate(pages):
            if candidate is page:
                return index
        return 0

    # ── watchdog ─────────────────────────────────────────────────────────────────

    async def _watch(self) -> None:
        """Follow the session's active page, and keep the URL/title current.

        Reading the title costs a driver round-trip, so it happens here — once per tick,
        shared by every frame in between — rather than per frame, where at stream rate it
        would dominate the cost of the stream itself.
        """
        while True:
            await asyncio.sleep(_WATCHDOG_INTERVAL_S)
            page = getattr(self._session, "page", None)
            if page is None:
                continue
            if page is not self._page:
                await self._detach()
                await self._attach(page)
                continue
            self._url = _page_url(page)
            try:
                self._title = await page.title()
            except Exception:  # noqa: BLE001 — a navigating page has no title yet
                pass


def _replace(queue: asyncio.Queue[Frame | None], item: Frame | None) -> None:
    """Put ``item`` in a one-slot queue, discarding whatever it displaced.

    Never awaits and never raises: this runs inside Chromium's event callback, where
    blocking would stall the CDP connection for every watcher at once.
    """
    with contextlib.suppress(asyncio.QueueEmpty):
        while queue.full():
            queue.get_nowait()
    with contextlib.suppress(asyncio.QueueFull):
        queue.put_nowait(item)


def _page_url(page: Any) -> str:
    try:
        return page.url or ""
    except Exception:  # noqa: BLE001 — a closing page can raise on attribute access
        return ""
