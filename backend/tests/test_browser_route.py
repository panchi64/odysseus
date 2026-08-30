"""The window onto the agent's browser: the frame socket, its status, and who has one.

A fake session manager stands in for the real one — what is worth guarding here is the
route's contract (token gating, the close codes the panel reads, the Origin check a
WebSocket does not get from CORS, and the two different credentials the two prefixes
carry), none of which needs a browser.
"""

from __future__ import annotations

import asyncio

from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import create_app
from core.config import Settings
from services.browser import Frame

ORIGIN = "http://localhost:5173"


class _FakeScreencast:
    """Hands out one pre-loaded queue, and records start/stop."""

    def __init__(self, frames: list[Frame | None]) -> None:
        self._frames = frames
        self.started = 0
        self.stopped = 0
        self.watchers = 0
        self._queues: list[asyncio.Queue] = []

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        for frame in self._frames:
            queue.put_nowait(frame)
        self._queues.append(queue)
        self.watchers += 1
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._queues.remove(queue)
        self.watchers -= 1

    async def start(self) -> None:
        self.started += 1

    async def stop(self) -> None:
        self.stopped += 1


class _FakeLive:
    def __init__(self, token: str, screencast: _FakeScreencast) -> None:
        self.token = token
        self.screencast = screencast
        self.page_url = "https://example.com/app"
        self.touches = 0

    def touch(self) -> None:
        self.touches += 1


class _FakeManager:
    """Resolves exactly one token, and knows one tombstone."""

    def __init__(self, live: _FakeLive | None, *, key: str = "c1", stopped: str = "gone") -> None:
        self._live = live
        self._key = key
        self._stopped = stopped

    def existing(self, key: str) -> _FakeLive | None:
        return self._live if key == self._key else None

    def resolve(self, token: str) -> _FakeLive | None:
        return self._live if self._live is not None and token == self._live.token else None

    def status(self, token: str) -> str:
        if self._live is not None and token == self._live.token:
            return "live"
        return "stopped" if token == self._stopped else "unknown"


def _frame(data: str = "AAAA") -> Frame:
    return Frame(
        data=data, width=1280, height=800, url="https://example.com/app",
        title="Example", tabs=1, active=0,
    )


def _refused_with(client: TestClient, path: str, **kwargs) -> int:
    """The close code a refused handshake came back with — the thing the panel reads."""
    try:
        with client.websocket_connect(path, **kwargs) as ws:
            ws.receive_text()
    except WebSocketDisconnect as exc:
        return exc.code
    raise AssertionError(f"{path} was accepted, expected a refusal")


def _app(tmp_path, manager: _FakeManager | None):
    settings = Settings(
        db_url="sqlite:///:memory:",
        data_dir=tmp_path,
        auth_enabled=False,
        unlock_passphrase="pw",
    )
    app = create_app(settings)
    client = TestClient(app)
    return app, client, manager


# --- the frame socket ------------------------------------------------------------------


def test_frames_reach_the_watcher_and_the_stream_starts_on_demand(tmp_path):
    # Streaming only runs while somebody is watching, so the first watcher starts it and
    # the last one to leave stops it — a session nobody opened the panel on costs nothing.
    screencast = _FakeScreencast([_frame("first"), None])
    live = _FakeLive("tok", screencast)
    app, client, manager = _app(tmp_path, _FakeManager(live))
    with client:
        app.state.browser_sessions = manager
        with client.websocket_connect("/browser/stream/tok") as ws:
            frame = ws.receive_json()
            assert frame["t"] == "frame"
            assert frame["data"] == "first"
            assert frame["url"] == "https://example.com/app"
            assert ws.receive_json() == {"t": "end", "reason": "stopped"}
    assert screencast.started == 1
    assert screencast.stopped == 1
    assert live.touches == 1  # watching keeps the browser from being reaped mid-stream


def test_an_unknown_token_and_a_reaped_one_close_differently(tmp_path):
    # The panel reads the two apart: 4410 means "there was a browser and it is gone",
    # 4404 means "no such session" — a stale link, or a restart.
    app, client, manager = _app(tmp_path, _FakeManager(None, stopped="gone"))
    with client:
        app.state.browser_sessions = manager
        for token, expected in (("gone", 4410), ("nonsense", 4404)):
            assert _refused_with(client, f"/browser/stream/{token}") == expected


def test_a_socket_from_another_page_is_refused(tmp_path):
    # `AuthMiddleware` returns early for non-HTTP scopes and CORS does not apply to
    # WebSockets, so the handshake has to check Origin itself.
    screencast = _FakeScreencast([_frame()])
    app, client, manager = _app(tmp_path, _FakeManager(_FakeLive("tok", screencast)))
    with client:
        app.state.browser_sessions = manager
        code = _refused_with(
            client, "/browser/stream/tok", headers={"origin": "https://evil.example"}
        )
        assert code == 1011
    assert screencast.started == 0  # refused before anything was subscribed


def test_the_frontend_origin_is_allowed(tmp_path):
    screencast = _FakeScreencast([_frame(), None])
    app, client, manager = _app(tmp_path, _FakeManager(_FakeLive("tok", screencast)))
    with client:
        app.state.browser_sessions = manager
        with client.websocket_connect(
            "/browser/stream/tok", headers={"origin": ORIGIN}
        ) as ws:
            assert ws.receive_json()["t"] == "frame"


# --- status and session lookup ---------------------------------------------------------


def test_status_tells_live_stopped_and_unknown_apart(tmp_path):
    app, client, manager = _app(tmp_path, _FakeManager(_FakeLive("tok", _FakeScreencast([]))))
    with client:
        app.state.browser_sessions = manager
        assert client.get("/browser/stream/tok/status").json() == {"status": "live"}
        assert client.get("/browser/stream/gone/status").json() == {"status": "stopped"}
        assert client.get("/browser/stream/nope/status").json() == {"status": "unknown"}


def test_a_conversation_reports_its_live_browser(tmp_path):
    # This is what makes the panel survive a page reload: the run event that announced the
    # session is long gone by then, and the manager is the source of truth for what is live.
    app, client, manager = _app(tmp_path, _FakeManager(_FakeLive("tok", _FakeScreencast([]))))
    with client:
        app.state.browser_sessions = manager
        body = client.get("/browser/session/c1").json()
        assert body == {
            "active": True,
            "url": "/browser/stream/tok",
            "page_url": "https://example.com/app",
        }
        assert client.get("/browser/session/other").json()["active"] is False


def test_no_browser_control_wired_is_not_an_error_for_a_conversation(tmp_path):
    # A thread simply has no browser; the panel must not have to special-case a 500.
    app, client, _ = _app(tmp_path, None)
    with client:
        app.state.browser_sessions = None
        assert client.get("/browser/session/c1").json()["active"] is False
        assert client.get("/browser/stream/tok/status").status_code == 503
