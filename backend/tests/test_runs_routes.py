"""Substrate HTTP surface: SSE streaming, resume, cancel, and 404s."""

from __future__ import annotations

import asyncio

from runs.events import AnswerDelta

from ._helpers import client_app, collect_sse_events


async def test_stream_delivers_full_event_record():
    async with client_app() as (client, app):

        async def orch(run):
            run.emit(AnswerDelta(text="hello"))

        run = app.state.runs.submit(kind="chat", owner_id="operator", orchestrator=orch)
        events = await collect_sse_events(client, run.id)

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
        events = await collect_sse_events(client, run.id, last_event_id=2)

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


async def test_list_runs_active_only_by_default():
    async with client_app() as (client, app):

        async def blocked(run):
            run.emit(AnswerDelta(text="working"))
            await asyncio.Event().wait()

        async def done(run):
            return None

        live = app.state.runs.submit(kind="chat", owner_id="operator", orchestrator=blocked)
        finished = app.state.runs.submit(kind="chat", owner_id="operator", orchestrator=done)
        await finished.wait()
        await asyncio.sleep(0)

        active = (await client.get("/runs")).json()
        assert {r["id"] for r in active} == {live.id}

        everything = (await client.get("/runs", params={"active": False})).json()
        assert {finished.id, live.id} <= {r["id"] for r in everything}

        await app.state.runs.cancel(live.id)
        await live.wait()


async def test_list_runs_empty():
    async with client_app() as (client, _app):
        assert (await client.get("/runs")).json() == []


async def test_unknown_run_is_404():
    async with client_app() as (client, _app):
        assert (await client.get("/runs/nope")).status_code == 404
        assert (await client.post("/runs/nope/cancel")).status_code == 404
        async with client.stream("GET", "/runs/nope/events") as resp:
            assert resp.status_code == 404
