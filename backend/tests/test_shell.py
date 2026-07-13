"""The Operator Shell (`SHELL-1..3`): the host-mode grant endpoint and the full
WebSocket auth-chain + PTY contract.

Host-mode grant assertions run on the async `client_app` helper (plain HTTP).
The WebSocket contract needs a client that can do *both* HTTP and WS on the
same app instance, which the async helper can't (`httpx` has no WS transport)
— those use a sync `fastapi.testclient.TestClient` instead, mirroring
`test_previews_route.py`'s own WebSocket tests.
"""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import create_app
from core.config import Settings
from core.ratelimit import RateLimiter
from services.host_shell import ShellService

from ._helpers import client_app

_PASSWORD = "test-passphrase"


# --- POST /shell/host-mode ------------------------------------------------------


async def test_host_mode_grant_succeeds_with_correct_password():
    async with client_app() as (client, _app):
        resp = await client.post("/shell/host-mode", json={"password": _PASSWORD})
        assert resp.status_code == 200
        body = resp.json()
        assert body["token"]
        assert body["expires_in_s"] > 0


async def test_host_mode_grant_rejects_wrong_password():
    async with client_app() as (client, _app):
        resp = await client.post("/shell/host-mode", json={"password": "wrong"})
        assert resp.status_code == 401


async def test_host_mode_grant_423_when_vault_locked():
    async with client_app() as (client, app):
        app.state.vault.lock()
        resp = await client.post("/shell/host-mode", json={"password": _PASSWORD})
        assert resp.status_code == 423


async def test_shell_disabled_returns_404():
    # shell_enabled=False is the kill-switch (`core/config.py`): the router must
    # not even be registered, and building the app with it off must not raise.
    # `client_app` (`_helpers.py`) doesn't expose a `shell_enabled` override, so
    # this mirrors its internals directly rather than widening that shared helper
    # for one test.
    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(
            db_url="sqlite:///:memory:",
            data_dir=Path(tmp),
            auth_enabled=False,
            unlock_passphrase=_PASSWORD,
            searxng_enabled=False,
            web_fetch_enabled=False,
            sandbox_enabled=False,
            offline_check_enabled=False,
            shell_enabled=False,
        )
        app = create_app(settings)
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post("/shell/host-mode", json={"password": _PASSWORD})
                assert resp.status_code == 404


async def test_host_mode_grant_rate_limited():
    async with client_app() as (client, app):
        # A 1-token bucket that never refills — the second attempt is throttled,
        # mirroring `test_uploads_routes.py`'s own rate-limit test.
        app.state.shell_auth_rate_limiter = RateLimiter(rate_per_second=0.0, burst=1)
        ok = await client.post("/shell/host-mode", json={"password": _PASSWORD})
        throttled = await client.post("/shell/host-mode", json={"password": _PASSWORD})
        assert ok.status_code == 200
        assert throttled.status_code == 429
        assert "retry-after" in throttled.headers


# --- the host-mode token store (unit-level) --------------------------------------


def test_host_token_is_rejected_once_its_ttl_elapses():
    settings = Settings(
        db_url="sqlite:///:memory:",
        data_dir=Path(tempfile.mkdtemp()),
        shell_host_token_ttl_s=0.01,
    )
    service = ShellService(settings=settings, vault=object(), auth_manager=object())
    token, ttl = service.mint_host_token()
    assert ttl == pytest.approx(0.01)
    time.sleep(0.05)
    assert service.consume_host_token(token) is False


# --- WS: the auth handshake + PTY contract ----------------------------------------


def _sync_app(tmp_path, **overrides):
    # `auth_enabled` defaults to False (most WS tests don't care about the bearer
    # gate) but must stay overridable — `test_ws_bearer_rejection_closes_4401`
    # flips it on — so it's popped out of `overrides` rather than hardcoded
    # alongside it.
    auth_enabled = overrides.pop("auth_enabled", False)
    settings = Settings(
        db_url="sqlite:///:memory:",
        data_dir=tmp_path,
        auth_enabled=auth_enabled,
        unlock_passphrase=_PASSWORD,
        searxng_enabled=False,
        web_fetch_enabled=False,
        sandbox_enabled=False,
        offline_check_enabled=False,
        **overrides,
    )
    return create_app(settings)


def _mint_token(client: TestClient) -> str:
    resp = client.post("/shell/host-mode", json={"password": _PASSWORD})
    assert resp.status_code == 200
    return resp.json()["token"]


def test_ws_full_round_trip(tmp_path):
    app = _sync_app(tmp_path)
    with TestClient(app) as client:
        token = _mint_token(client)
        with client.websocket_connect("/shell/ws") as ws:
            ws.send_text(json.dumps({"type": "auth", "bearer": "", "host": token}))
            assert ws.receive_json() == {"type": "ready"}

            ws.send_text(json.dumps({"type": "stdin", "data": "echo hi\n"}))
            collected = b""
            deadline = time.monotonic() + 10
            while b"hi" not in collected and time.monotonic() < deadline:
                collected += ws.receive_bytes()
            assert b"hi" in collected

            # A resize must not crash the session.
            ws.send_text(json.dumps({"type": "resize", "cols": 100, "rows": 40}))
            ws.send_text(json.dumps({"type": "stdin", "data": "echo still-alive\n"}))
            deadline = time.monotonic() + 10
            while b"still-alive" not in collected and time.monotonic() < deadline:
                collected += ws.receive_bytes()
            assert b"still-alive" in collected


def test_ws_missing_host_token_closes_4403(tmp_path):
    app = _sync_app(tmp_path)
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as excinfo:
            with client.websocket_connect("/shell/ws") as ws:
                ws.send_text(json.dumps({"type": "auth", "bearer": "", "host": ""}))
                ws.receive_text()
        assert excinfo.value.code == 4403


def test_ws_host_token_is_single_use(tmp_path):
    app = _sync_app(tmp_path)
    with TestClient(app) as client:
        token = _mint_token(client)
        with client.websocket_connect("/shell/ws") as ws:
            ws.send_text(json.dumps({"type": "auth", "bearer": "", "host": token}))
            assert ws.receive_json() == {"type": "ready"}

        with pytest.raises(WebSocketDisconnect) as excinfo:
            with client.websocket_connect("/shell/ws") as ws2:
                ws2.send_text(json.dumps({"type": "auth", "bearer": "", "host": token}))
                ws2.receive_text()
        assert excinfo.value.code == 4403


def test_vault_lock_kills_live_session(tmp_path):
    app = _sync_app(tmp_path)
    with TestClient(app) as client:
        token = _mint_token(client)
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/shell/ws") as ws:
                ws.send_text(json.dumps({"type": "auth", "bearer": "", "host": token}))
                assert ws.receive_json() == {"type": "ready"}
                # Locking the vault (the real trigger — routes/auth.py's
                # POST /auth/lock — runs on the app's own event loop, unlike
                # poking app.state.vault directly from the test thread).
                assert client.post("/auth/lock").status_code == 200
                ws.receive_text()  # the session was torn down by the lock hook


def test_ws_bearer_rejection_closes_4401(tmp_path):
    # auth_enabled=True with no valid session token in play — the bearer check
    # runs before the host-mode token is even looked at, so a garbage bearer is
    # rejected without needing a real login or a minted token. This also confirms
    # the ASGI auth gate lets the WS upgrade itself through (it only guards the
    # http scope) so `open_session`'s own auth chain is what actually runs.
    app = _sync_app(tmp_path, auth_enabled=True)
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as excinfo:
            with client.websocket_connect("/shell/ws") as ws:
                ws.send_text(json.dumps({"type": "auth", "bearer": "garbage", "host": ""}))
                ws.receive_text()
        assert excinfo.value.code == 4401


def test_ws_idle_timeout_closes_4403(tmp_path):
    app = _sync_app(tmp_path, shell_idle_timeout_s=0.05)
    with TestClient(app) as client:
        token = _mint_token(client)
        with pytest.raises(WebSocketDisconnect) as excinfo:
            with client.websocket_connect("/shell/ws") as ws:
                ws.send_text(json.dumps({"type": "auth", "bearer": "", "host": token}))
                assert ws.receive_json() == {"type": "ready"}
                # No stdin at all — the idle watcher must tear the session down
                # on its own.
                ws.receive_text()
        assert excinfo.value.code == 4403


def test_ws_concurrent_session_limit_closes_4409(tmp_path):
    # shell_max_sessions defaults to 1 — a second connection while the first is
    # still open must be rejected as busy, even with its own valid, unspent
    # host-mode token.
    app = _sync_app(tmp_path)
    with TestClient(app) as client:
        token1 = _mint_token(client)
        token2 = _mint_token(client)
        with client.websocket_connect("/shell/ws") as ws1:
            ws1.send_text(json.dumps({"type": "auth", "bearer": "", "host": token1}))
            assert ws1.receive_json() == {"type": "ready"}

            with pytest.raises(WebSocketDisconnect) as excinfo:
                with client.websocket_connect("/shell/ws") as ws2:
                    ws2.send_text(json.dumps({"type": "auth", "bearer": "", "host": token2}))
                    ws2.receive_text()
            assert excinfo.value.code == 4409
