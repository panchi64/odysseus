"""POST /chat creates a Run that streams over the substrate SSE surface."""

from __future__ import annotations

from pydantic_ai.models.test import TestModel

from services.registry import ModelRegistry

from ._helpers import client_app, collect_sse_events


async def _fake_resolve(self, role, *, owner_id, override_endpoint_id=None):
    """Stand in for registry resolution — a TestModel needs no real server."""
    return TestModel(custom_output_text="hi")


async def test_chat_creates_run_and_streams_answer(monkeypatch):
    # The route resolves the `main` role through the registry; point that at a
    # TestModel so the turn runs without a live model server.
    monkeypatch.setattr(ModelRegistry, "resolve", _fake_resolve)

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
    monkeypatch.setattr(ModelRegistry, "resolve", _fake_resolve)

    async with client_app() as (client, _app):
        resp = await client.post(
            "/chat", json={"prompt": "hello", "conversation_id": "does-not-exist"}
        )
        assert resp.status_code == 404
