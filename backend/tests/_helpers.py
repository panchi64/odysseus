"""Shared test helpers: a booted app + client, and an SSE event collector."""

from __future__ import annotations

import json
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

import httpx

from app import create_app
from core.config import Settings


@asynccontextmanager
async def client_app(*, auth_enabled: bool = False, passphrase: str | None = "test-passphrase"):
    """A booted app + async client, backed by a throwaway in-memory DB.

    An in-memory SQLite URL plus a temp data dir (for the keyfile) keep tests off
    the real ``data/`` dir. By default auth is off and a passphrase unlocks the
    vault at boot, so feature endpoints are reachable without a token; the auth
    tests pass ``auth_enabled=True, passphrase=None`` to exercise setup/login.
    """
    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(
            db_url="sqlite:///:memory:",
            data_dir=Path(tmp),
            auth_enabled=auth_enabled,
            unlock_passphrase=passphrase,
        )
        app = create_app(settings)
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                yield client, app


async def collect_sse_events(client, run_id, *, last_event_id=None):
    """Drain a run's SSE stream to a list of decoded event envelopes."""
    params = {} if last_event_id is None else {"last_event_id": last_event_id}
    events = []
    async with client.stream("GET", f"/runs/{run_id}/events", params=params) as resp:
        assert resp.status_code == 200
        async for line in resp.aiter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[len("data:") :].strip()))
    return events
