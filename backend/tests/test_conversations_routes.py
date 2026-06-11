"""The conversations REST surface — list, read (projected history), rename, delete.

A conversation comes into being as a side effect of a chat turn, so each test
drives ``POST /chat`` (against a TestModel) to create one, then exercises the
read/manage endpoints over it.
"""

from __future__ import annotations

from pydantic_ai.models.test import TestModel

from services.registry import ModelRegistry

from ._helpers import client_app, collect_sse_events


async def _fake_resolve(self, role, *, owner_id, override_endpoint_id=None):
    """A plain text turn with no tool calls — keeps the stream completable."""
    return TestModel(custom_output_text="hello there", call_tools=[])


async def _start_conversation(client, prompt: str = "say hi") -> str:
    """Run one chat turn and return its conversation id, draining the stream so
    the turn's messages are recorded before we read them back."""
    resp = await client.post("/chat", json={"prompt": prompt})
    assert resp.status_code == 202
    body = resp.json()
    await collect_sse_events(client, body["run_id"])
    return body["conversation_id"]


async def test_list_conversations(monkeypatch):
    monkeypatch.setattr(ModelRegistry, "resolve", _fake_resolve)
    async with client_app() as (client, _app):
        conversation_id = await _start_conversation(client)

        resp = await client.get("/conversations")
        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) == 1
        row = rows[0]
        assert row["id"] == conversation_id
        assert row["message_count"] == 2  # user prompt + assistant answer
        assert row["preview"]  # derived from the latest message text


async def test_get_conversation_projects_history(monkeypatch):
    monkeypatch.setattr(ModelRegistry, "resolve", _fake_resolve)
    async with client_app() as (client, _app):
        conversation_id = await _start_conversation(client, prompt="say hi")

        resp = await client.get(f"/conversations/{conversation_id}")
        assert resp.status_code == 200
        detail = resp.json()
        assert detail["id"] == conversation_id
        messages = detail["messages"]
        assert [m["role"] for m in messages] == ["user", "assistant"]
        assert messages[0]["content"] == "say hi"
        assert messages[1]["content"] == "hello there"
        assert messages[1]["tools"] == []


async def test_get_unknown_conversation_404():
    async with client_app() as (client, _app):
        resp = await client.get("/conversations/does-not-exist")
        assert resp.status_code == 404


async def test_rename_conversation(monkeypatch):
    monkeypatch.setattr(ModelRegistry, "resolve", _fake_resolve)
    async with client_app() as (client, _app):
        conversation_id = await _start_conversation(client)

        resp = await client.patch(
            f"/conversations/{conversation_id}", json={"title": "Migration plan"}
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Migration plan"

        detail = await client.get(f"/conversations/{conversation_id}")
        assert detail.json()["title"] == "Migration plan"


async def test_rename_unknown_conversation_404():
    async with client_app() as (client, _app):
        resp = await client.patch("/conversations/nope", json={"title": "x"})
        assert resp.status_code == 404


async def test_delete_conversation(monkeypatch):
    monkeypatch.setattr(ModelRegistry, "resolve", _fake_resolve)
    async with client_app() as (client, _app):
        conversation_id = await _start_conversation(client)

        resp = await client.delete(f"/conversations/{conversation_id}")
        assert resp.status_code == 204

        assert (await client.get(f"/conversations/{conversation_id}")).status_code == 404
        assert (await client.get("/conversations")).json() == []


async def test_delete_unknown_conversation_404():
    async with client_app() as (client, _app):
        resp = await client.delete("/conversations/nope")
        assert resp.status_code == 404
