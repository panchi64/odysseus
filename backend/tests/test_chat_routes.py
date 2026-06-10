"""POST /chat creates a Run that streams over the substrate SSE surface."""

from __future__ import annotations

from pydantic_ai.models.test import TestModel

import services.llm as llm

from ._helpers import client_app, collect_sse_events


async def test_chat_creates_run_and_streams_answer(monkeypatch):
    # The route resolves the `main` role; point it at a TestModel (no server).
    def fake_resolve(role="main"):
        return TestModel(custom_output_text="hi")

    monkeypatch.setattr(llm, "resolve_model", fake_resolve)

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
    def fake_resolve(role="main"):
        return TestModel(custom_output_text="hi")

    monkeypatch.setattr(llm, "resolve_model", fake_resolve)

    async with client_app() as (client, _app):
        resp = await client.post(
            "/chat", json={"prompt": "hello", "conversation_id": "does-not-exist"}
        )
        assert resp.status_code == 404
