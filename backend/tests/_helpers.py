"""Shared test helpers: a booted app + client, and an SSE event collector."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager

import httpx

from app import create_app
from core.config import Settings


@asynccontextmanager
async def client_app():
    """A booted app + async client, backed by a throwaway in-memory DB.

    Uses an in-memory SQLite URL so tests never touch the real ``data/`` dir.
    """
    app = create_app(Settings(db_url="sqlite:///:memory:"))
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
