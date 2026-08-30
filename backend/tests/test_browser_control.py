"""Browser control: the conversation-scoped session, its frame stream, and the tools.

Three layers, fastest-first:
- ``Screencast`` — the CDP frame pump, over a fake CDP session (no browser).
- ``BrowserSessionManager`` — acquire/reap/evict and the degrade path (fake sessions).
- the toolset — that two conversations drive two *pages*, not merely two toolsets.

Nothing here starts Chromium: what is worth guarding is the wiring around the harness's
browser, and a container would make these tests slow, flaky, and environment-dependent
without testing more of our own code.
"""

from __future__ import annotations

import asyncio

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from core.container import ServiceContainer
from runs import Run, RunStream
from services.browser import BrowserSessionManager, LiveBrowser, Screencast
from services.browser.session import ControlledBrowserSession
from tools import RunDeps
from tools.browse import TOOL_NAMES, browse_toolset

OWNER = "operator"


# --- fakes -----------------------------------------------------------------------------


class _FakeCdp:
    """Records what the screencast sends, and lets a test push frames in."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, dict | None]] = []
        self.detached = False
        self._handlers: dict[str, list] = {}

    def on(self, event: str, handler) -> None:
        self._handlers.setdefault(event, []).append(handler)

    async def send(self, method: str, params: dict | None = None) -> None:
        self.sent.append((method, params))

    async def detach(self) -> None:
        self.detached = True

    def push(self, data: str = "AAAA", session_id: int = 1) -> None:
        for handler in self._handlers.get("Page.screencastFrame", []):
            handler(
                {
                    "data": data,
                    "sessionId": session_id,
                    "metadata": {"deviceWidth": 1280, "deviceHeight": 800},
                }
            )

    def acks(self) -> list[dict | None]:
        return [params for method, params in self.sent if method == "Page.screencastFrameAck"]


class _FakeContext:
    def __init__(self, cdp: _FakeCdp) -> None:
        self._cdp = cdp

    async def new_cdp_session(self, _page) -> _FakeCdp:
        return self._cdp


class _FailingContext(_FakeContext):
    """A context whose CDP session can't be opened — a page mid-navigation, or a browser
    that went away between the attach decision and the attach."""

    async def new_cdp_session(self, _page) -> _FakeCdp:
        raise RuntimeError("target closed")


class _FakePage:
    def __init__(self, url: str = "https://example.com", cdp: _FakeCdp | None = None) -> None:
        self.url = url
        self.context = _FakeContext(cdp or _FakeCdp())
        self.init_scripts: list[str] = []

    async def title(self) -> str:
        return "Example"

    async def add_init_script(self, script: str) -> None:
        self.init_scripts.append(script)


class _FakeSession:
    """Stands in for a harness browser session: an active page and the open tabs."""

    def __init__(self, page: _FakePage) -> None:
        self.page = page
        self.pages = [page]
        self.exited = False

    async def __aexit__(self, *_args) -> None:
        self.exited = True


class _FakeManaged:
    """A ManagedBrowser stand-in whose availability a test can flip."""

    def __init__(self, cdp_url: str | None = "http://127.0.0.1:9222") -> None:
        self.cdp_url = cdp_url
        self.stealthed: list[_FakePage] = []

    async def apply_stealth(self, page) -> None:
        self.stealthed.append(page)


def _manager(managed: _FakeManaged, **kwargs) -> BrowserSessionManager:
    options = {"idle_ttl_s": 900.0, "reap_interval_s": 60.0, "max_live": 3} | kwargs
    return BrowserSessionManager(managed, **options)  # type: ignore[arg-type]


def _live(manager: BrowserSessionManager, key: str, page: _FakePage | None = None) -> LiveBrowser:
    """Install a fake session under ``key``, bypassing the real CDP attach."""
    session = _FakeSession(page or _FakePage())
    live = LiveBrowser(key, f"token-{key}", session, Screencast(session))  # type: ignore[arg-type]
    manager._sessions[key] = live  # noqa: SLF001 — constructing the state under test
    manager._tokens[live.token] = key  # noqa: SLF001
    return live


# --- the frame pump --------------------------------------------------------------------


async def test_every_frame_is_acked_exactly_once():
    # The ack is the flow control: Chromium withholds the next frame until it arrives, so
    # a missed one stalls the stream and a doubled one is a protocol error.
    cdp = _FakeCdp()
    session = _FakeSession(_FakePage(cdp=cdp))
    cast = Screencast(session)  # type: ignore[arg-type]
    queue = cast.subscribe()
    await cast.start()

    cdp.push()
    cdp.push()
    await asyncio.sleep(0)  # let the fire-and-forget ack tasks run
    await asyncio.sleep(0)

    assert cdp.acks() == [{"sessionId": 1}, {"sessionId": 1}]
    assert queue.qsize() == 1
    await cast.stop()


async def test_a_slow_watcher_sees_the_newest_frame_not_a_backlog():
    # A stream of screenshots has no history worth keeping: a watcher that fell behind
    # wants what the page shows *now*, not to replay the last few seconds at a delay.
    cdp = _FakeCdp()
    session = _FakeSession(_FakePage(cdp=cdp))
    cast = Screencast(session)  # type: ignore[arg-type]
    queue = cast.subscribe()
    await cast.start()

    cdp.push(data="first")
    cdp.push(data="second")
    cdp.push(data="third")

    assert queue.qsize() == 1
    frame = queue.get_nowait()
    assert frame is not None and frame.data == "third"
    await cast.stop()


async def test_stopping_detaches_and_stops_the_stream():
    cdp = _FakeCdp()
    session = _FakeSession(_FakePage(cdp=cdp))
    cast = Screencast(session)  # type: ignore[arg-type]
    await cast.start()
    await cast.stop()

    assert ("Page.stopScreencast", None) in cdp.sent
    assert cdp.detached
    # No ack can follow a stop — the CDP session is gone.
    cdp.push()
    await asyncio.sleep(0)
    assert cdp.acks() == []


async def test_a_second_watcher_does_not_start_a_second_watchdog():
    # An attach that failed leaves no CDP session but the watchdog that will retry it;
    # a second `start()` must join that, not spawn a rival that detaches what it attaches
    # — and `stop()` could only ever cancel whichever one the field happened to hold.
    page = _FakePage()
    page.context = _FailingContext(_FakeCdp())  # type: ignore[assignment]
    cast = Screencast(_FakeSession(page))  # type: ignore[arg-type]

    await cast.start()
    first = cast._watchdog  # noqa: SLF001 — the task identity is the whole assertion
    assert first is not None
    assert cast._cdp is None  # noqa: SLF001 — the attach failed, as arranged

    await cast.start()  # a second watcher joins

    assert cast._watchdog is first  # noqa: SLF001
    await cast.stop()
    assert cast._watchdog is None  # noqa: SLF001


async def test_acks_are_held_until_they_complete():
    # The loop keeps only a weak reference to a task, and a collected ack does not fail
    # loudly — it silently freezes the stream, since Chromium withholds the next frame.
    cdp = _FakeCdp()
    session = _FakeSession(_FakePage(cdp=cdp))
    cast = Screencast(session)  # type: ignore[arg-type]
    cast.subscribe()
    await cast.start()

    cdp.push()
    assert len(cast._acks) == 1  # noqa: SLF001 — referenced, so it cannot be collected
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert cast._acks == set()  # noqa: SLF001 — and released once it has sent
    assert cdp.acks() == [{"sessionId": 1}]
    await cast.stop()


async def test_closing_wakes_every_watcher_with_the_end_sentinel():
    # The stop signal reaches the panel on its own socket, because a reap happens between
    # turns when there is no run stream to carry an event.
    session = _FakeSession(_FakePage())
    cast = Screencast(session)  # type: ignore[arg-type]
    first, second = cast.subscribe(), cast.subscribe()

    cast.close()

    assert first.get_nowait() is None
    assert second.get_nowait() is None
    assert cast.watchers == 0


async def test_the_frame_envelope_carries_the_page_chrome():
    # Metadata rides on every frame so a watcher that joins mid-stream is immediately
    # correct — never a new page shown under the previous page's URL.
    cdp = _FakeCdp()
    session = _FakeSession(_FakePage(url="https://example.com/app", cdp=cdp))
    cast = Screencast(session)  # type: ignore[arg-type]
    queue = cast.subscribe()
    await cast.start()
    cdp.push(data="xyz")

    envelope = queue.get_nowait().envelope()  # type: ignore[union-attr]
    assert envelope["t"] == "frame"
    assert envelope["data"] == "xyz"
    assert envelope["url"] == "https://example.com/app"
    assert (envelope["w"], envelope["h"]) == (1280, 800)
    assert (envelope["tabs"], envelope["active"]) == (1, 0)
    await cast.stop()


# --- the session manager ---------------------------------------------------------------


async def test_no_browser_to_attach_to_degrades_rather_than_raising():
    manager = _manager(_FakeManaged(cdp_url=None))
    assert await manager.acquire("c1") is None


async def test_a_conversation_keeps_one_session_across_turns():
    manager = _manager(_FakeManaged())
    live = _live(manager, "c1")
    # Two sequential turns: the second must find the first turn's browser, not open one.
    assert await manager.acquire("c1") is live
    assert await manager.acquire("c1") is live
    assert manager.existing("c1") is live


async def test_two_conversations_get_two_sessions():
    manager = _manager(_FakeManaged())
    first, second = _live(manager, "c1"), _live(manager, "c2")
    assert first is not second
    assert first.session.page is not second.session.page  # type: ignore[union-attr]


async def test_a_token_resolves_only_to_its_own_session():
    manager = _manager(_FakeManaged())
    live = _live(manager, "c1")
    assert manager.resolve(live.token) is live
    assert manager.resolve("not-a-token") is None
    assert manager.status(live.token) == "live"
    assert manager.status("not-a-token") == "unknown"


async def test_a_reaped_session_reports_stopped_not_unknown():
    # The distinction is what lets the panel say "the browser was closed" instead of
    # failing silently on a token the backend simply doesn't recognize.
    manager = _manager(_FakeManaged(), idle_ttl_s=0.0)
    live = _live(manager, "c1")
    await manager._sweep()  # noqa: SLF001 — driving the reaper directly, no clock wait

    assert manager.existing("c1") is None
    assert manager.status(live.token) == "stopped"
    assert live.session.exited  # type: ignore[union-attr]


async def test_the_browser_going_away_reaps_every_session():
    # This is how offline mode reaches the manager without knowing it exists: suspending
    # web fetch stops the container, and `cdp_url` going None clears what attached to it.
    managed = _FakeManaged()
    manager = _manager(managed)
    first, second = _live(manager, "c1"), _live(manager, "c2")

    managed.cdp_url = None
    await manager._sweep()  # noqa: SLF001

    assert manager.existing("c1") is None and manager.existing("c2") is None
    assert manager.status(first.token) == "stopped"
    assert manager.status(second.token) == "stopped"


async def test_the_live_cap_evicts_the_least_recently_used():
    manager = _manager(_FakeManaged(), max_live=2)
    oldest, middle, newest = (_live(manager, k) for k in ("c1", "c2", "c3"))
    oldest._last_used -= 100  # noqa: SLF001 — make the LRU order unambiguous
    middle._last_used -= 50  # noqa: SLF001

    await manager._enforce_cap()  # noqa: SLF001

    assert manager.existing("c1") is None
    assert manager.existing("c2") is middle
    assert manager.existing("c3") is newest
    assert oldest.session.exited  # type: ignore[union-attr]


async def test_creation_locks_do_not_accumulate_forever():
    # Every other map here is bounded or reaped; the per-conversation creation locks were
    # the one structure that only ever grew — an entry per conversation that ever browsed.
    manager = _manager(_FakeManaged(cdp_url=None), idle_ttl_s=0.0)
    for key in ("c1", "c2", "c3"):
        await manager.acquire(key)  # degrades (no browser), but takes a lock on the way
    assert len(manager._creating) == 3  # noqa: SLF001

    live = _live(manager, "c4")
    manager._creating.setdefault("c4", asyncio.Lock())  # noqa: SLF001
    await manager._sweep()  # noqa: SLF001

    # The three that hold nothing are gone; c4's went with its own reaped session.
    assert manager._creating == {}  # noqa: SLF001
    assert live.session.exited  # type: ignore[union-attr]


async def test_stop_tears_every_session_down():
    manager = _manager(_FakeManaged())
    live = _live(manager, "c1")
    await manager.stop()
    assert manager.existing("c1") is None
    assert live.session.exited  # type: ignore[union-attr]


async def test_teardown_leaves_the_shared_browser_alone():
    # The container Chromium belongs to web fetch and is still serving it; a session that
    # merely attached must never close it.
    session = ControlledBrowserSession(cdp_url="http://127.0.0.1:9222")
    closed: list[bool] = []

    class _Handle:
        async def close(self) -> None:
            closed.append(True)

    session._browser = _Handle()  # noqa: SLF001 — the handle teardown would close
    await session.__aexit__(None, None, None)

    assert closed == []


# --- the tools -------------------------------------------------------------------------


def _ctx(caps: ServiceContainer, conversation_id: str) -> RunContext[RunDeps]:
    run = Run(id=f"run-{conversation_id}", kind="chat", owner_id=OWNER, stream=RunStream())
    deps = RunDeps(run=run, owner_id=OWNER, caps=caps, conversation_id=conversation_id)
    return RunContext(deps=deps, model=TestModel(), usage=RunUsage())


async def test_the_catalog_matches_the_harness_toolset():
    # The namespaced names are written out in `tools/browse.py` for the offline and vision
    # gates; if the harness renames a tool, the gate would silently stop covering it.
    assert set(browse_toolset().tools) == TOOL_NAMES


async def test_the_tools_degrade_when_there_is_no_session_manager():
    toolset = browse_toolset()
    refusal = await toolset.bind("navigate", _ctx(ServiceContainer(), "c1"))
    assert isinstance(refusal, str) and "not available" in refusal


async def test_the_tools_degrade_when_no_browser_can_be_attached():
    caps = ServiceContainer()
    caps.add(_manager(_FakeManaged(cdp_url=None)))
    refusal = await browse_toolset().bind("navigate", _ctx(caps, "c1"))
    assert isinstance(refusal, str) and "not available" in refusal


async def test_two_conversations_drive_two_pages_not_two_toolsets():
    # The trap `tools/rebound.py` documents: asserting only "the toolsets differ" passes
    # while both dispatch onto the template's page. Assert the *pages* differ and each is
    # its own conversation's.
    manager = _manager(_FakeManaged())
    caps = ServiceContainer()
    caps.add(manager)
    first_live, second_live = _live(manager, "c1"), _live(manager, "c2")
    toolset = browse_toolset()

    first = await toolset.bind("navigate", _ctx(caps, "c1"))
    second = await toolset.bind("navigate", _ctx(caps, "c2"))

    assert not isinstance(first, str) and not isinstance(second, str)
    assert first is not second
    assert first._session is first_live.session  # noqa: SLF001 — the page each drives
    assert second._session is second_live.session  # noqa: SLF001


async def test_the_live_browser_is_announced_once_per_run():
    # The panel opens the moment the agent first touches a page; re-announcing on every
    # one of eighteen tools would have it reopening all turn.
    manager = _manager(_FakeManaged())
    caps = ServiceContainer()
    caps.add(manager)
    live = _live(manager, "c1")
    toolset = browse_toolset()
    ctx = _ctx(caps, "c1")

    await toolset.bind("navigate", ctx)
    await toolset.bind("click", ctx)

    announced = [e.body for e in ctx.deps.run.stream.replay() if e.body.type == "browser.live"]
    assert len(announced) == 1
    assert announced[0].url == f"/browser/stream/{live.token}"
    assert announced[0].conversation_id == "c1"


async def test_a_new_session_gets_a_new_binding():
    # A reaped conversation re-attaches under a *new* session; a toolset cached by
    # conversation would keep driving the dead one.
    manager = _manager(_FakeManaged())
    caps = ServiceContainer()
    caps.add(manager)
    toolset = browse_toolset()

    _live(manager, "c1")
    before = await toolset.bind("navigate", _ctx(caps, "c1"))
    await manager.release("c1")
    _live(manager, "c1", page=_FakePage(url="https://example.com/after"))
    manager._sessions["c1"].token = "token-fresh"  # noqa: SLF001 — a genuinely new session
    manager._tokens["token-fresh"] = "c1"  # noqa: SLF001
    after = await toolset.bind("navigate", _ctx(caps, "c1"))

    assert before is not after


@pytest.mark.parametrize("name", sorted(TOOL_NAMES))
def test_every_tool_is_declared_network_dependent(name: str):
    # Every browse tool *is* the internet: offline mode must withhold all of them, not
    # the subset someone remembered.
    from tools.browse import NETWORK_TOOLS

    assert f"browse_{name}" in NETWORK_TOOLS
