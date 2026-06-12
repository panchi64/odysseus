"""POST /chat creates a Run that streams over the substrate SSE surface."""

from __future__ import annotations

from ._helpers import client_app, collect_sse_events, patch_model_resolution


async def test_chat_creates_run_and_streams_answer(monkeypatch):
    # The route resolves the `main` role through the registry; point that at a
    # TestModel so the turn runs without a live model server.
    patch_model_resolution(monkeypatch)

    async with client_app() as (client, _app):
        resp = await client.post("/chat", json={"prompt": "say hi"})
        assert resp.status_code == 202
        run_id = resp.json()["run_id"]

        events = await collect_sse_events(client, run_id)

    types = [e["type"] for e in events]
    assert types[0] == "run.started"
    assert types[-1] == "run.ended"
    answer = "".join(e["text"] for e in events if e["type"] == "answer.delta")
    assert answer == "hi"


async def test_chat_requires_prompt():
    async with client_app() as (client, _app):
        resp = await client.post("/chat", json={})
        assert resp.status_code == 422


async def test_chat_rejects_unknown_conversation(monkeypatch):
    # A client-supplied conversation_id that doesn't exist must 404, not silently
    # spawn orphan messages under a phantom conversation.
    patch_model_resolution(monkeypatch)

    async with client_app() as (client, _app):
        resp = await client.post(
            "/chat", json={"prompt": "hello", "conversation_id": "does-not-exist"}
        )
        assert resp.status_code == 404
