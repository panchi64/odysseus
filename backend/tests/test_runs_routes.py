"""Substrate HTTP surface: SSE streaming, resume, cancel, and 404s."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager

import httpx

from app import create_app
from runs.events import AnswerDelta


@asynccontextmanager
async def client_app():
    """A booted app (lifespan run, so app.state.runs exists) + an async client."""
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, app


async def _collect_events(client, run_id, *, last_event_id=None):
    params = {} if last_event_id is None else {"last_event_id": last_event_id}
    events = []
    async with client.stream("GET", f"/runs/{run_id}/events", params=params) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        async for line in resp.aiter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[len("data:") :].strip()))
    return events


async def test_stream_delivers_full_event_record():
    async with client_app() as (client, app):

        async def orch(run):
            run.emit(AnswerDelta(text="hello"))

        run = app.state.runs.submit(kind="chat", owner_id="operator", orchestrator=orch)
        events = await _collect_events(client, run.id)

    types = [e["type"] for e in events]
    assert types[0] == "run.started"
    assert "answer.delta" in types
    assert types[-1] == "run.ended"
    assert [e["seq"] for e in events] == sorted(e["seq"] for e in events)


async def test_resume_replays_only_missed_events():
    async with client_app() as (client, app):

        async def orch(run):
            run.emit(AnswerDelta(text="a"))
            run.emit(AnswerDelta(text="b"))

        run = app.state.runs.submit(kind="chat", owner_id="operator", orchestrator=orch)
        await run.wait()
        events = await _collect_events(client, run.id, last_event_id=2)

    assert all(e["seq"] > 2 for e in events)
    assert events[-1]["type"] == "run.ended"


async def test_cancel_endpoint():
    async with client_app() as (client, app):

        async def orch(run):
            run.emit(AnswerDelta(text="working"))
            await asyncio.Event().wait()

        run = app.state.runs.submit(kind="agent", owner_id="operator", orchestrator=orch)
        await asyncio.sleep(0)

        resp = await client.post(f"/runs/{run.id}/cancel")
        assert resp.status_code == 202
        await run.wait()

        status = await client.get(f"/runs/{run.id}")
        assert status.json()["status"] == "cancelled"


async def test_cancel_terminal_run_conflicts():
    async with client_app() as (client, app):

        async def orch(run):
            return None

        run = app.state.runs.submit(kind="chat", owner_id="operator", orchestrator=orch)
        await run.wait()
        resp = await client.post(f"/runs/{run.id}/cancel")
        assert resp.status_code == 409


async def test_unknown_run_is_404():
    async with client_app() as (client, _app):
        assert (await client.get("/runs/nope")).status_code == 404
        assert (await client.post("/runs/nope/cancel")).status_code == 404
        async with client.stream("GET", "/runs/nope/events") as resp:
            assert resp.status_code == 404
