"""The two questions the app asks about the agent's browser: who has one, and open one.

A fake session manager stands in for the real one — what is worth guarding here is the
route's contract (a thread with no browser is not an error, opening one focuses it, and a
window that cannot be launched says so rather than reporting a success), none of which
needs a browser.
"""

from __future__ import annotations

from starlette.testclient import TestClient

from app import create_app
from core.config import Settings


class _FakeLive:
    def __init__(self, token: str = "tok") -> None:
        self.token = token
        self.page_url = "https://example.com/app"


class _FakeManager:
    """Holds one conversation's browser, and records how it was asked for."""

    def __init__(self, live: _FakeLive | None, *, key: str = "c1") -> None:
        self._live = live
        self._key = key
        self.acquired: list[tuple[str, bool]] = []

    def existing(self, key: str) -> _FakeLive | None:
        return self._live if key == self._key else None

    async def acquire(self, key: str, *, focus: bool = False) -> _FakeLive | None:
        self.acquired.append((key, focus))
        return self._live


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


# --- session lookup --------------------------------------------------------------------


def test_a_conversation_reports_its_live_browser(tmp_path):
    # What a freshly-loaded page reads: the run events that touched the browser are long
    # gone by then, and the manager is the source of truth for what is live right now.
    app, client, manager = _app(tmp_path, _FakeManager(_FakeLive()))
    with client:
        app.state.browser_sessions = manager
        assert client.get("/browser/session/c1").json() == {
            "active": True,
            "page_url": "https://example.com/app",
        }
        assert client.get("/browser/session/other").json()["active"] is False
    assert manager.acquired == []  # asking never opens one


def test_no_browser_control_wired_is_not_an_error_for_a_conversation(tmp_path):
    # A thread simply has no browser; the UI must not have to special-case a 500.
    app, client, _ = _app(tmp_path, None)
    with client:
        app.state.browser_sessions = None
        assert client.get("/browser/session/c1").json()["active"] is False


# --- opening one -----------------------------------------------------------------------


def test_opening_a_browser_attaches_it_and_brings_the_window_forward(tmp_path):
    # The operator asked for a window: one that opened behind the app would look like
    # nothing happened, so this is the one caller that passes `focus`.
    app, client, manager = _app(tmp_path, _FakeManager(_FakeLive()))
    with client:
        app.state.browser_sessions = manager
        body = client.post("/browser/session/c1")
        assert body.status_code == 200
        assert body.json() == {"active": True, "page_url": "https://example.com/app"}
    assert manager.acquired == [("c1", True)]


def test_a_browser_that_cannot_be_opened_is_a_503_with_a_reason(tmp_path):
    app, client, manager = _app(tmp_path, _FakeManager(None))
    with client:
        app.state.browser_sessions = manager
        response = client.post("/browser/session/c1")
        assert response.status_code == 503
        assert response.json()["detail"]


def test_opening_one_with_no_browser_control_wired_is_a_503(tmp_path):
    # Unlike the lookup, a request to *open* a window must never report success quietly.
    app, client, _ = _app(tmp_path, None)
    with client:
        app.state.browser_sessions = None
        assert client.post("/browser/session/c1").status_code == 503
