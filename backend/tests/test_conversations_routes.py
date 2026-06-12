"""The conversations REST surface — list, read (projected history), rename, delete.

A conversation comes into being as a side effect of a chat turn, so each test
drives ``POST /chat`` (against a TestModel) to create one, then exercises the
read/manage endpoints over it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from routes.conversations import _message_artifacts
from services.artifacts import ArtifactView, format_publish_result
from services.conversation_view import MessageView, ToolView

from ._helpers import client_app, collect_sse_events, patch_model_resolution


async def _start_conversation(client, prompt: str = "say hi") -> str:
    """Run one chat turn and return its conversation id, draining the stream so
    the turn's messages are recorded before we read them back."""
    resp = await client.post("/chat", json={"prompt": prompt})
    assert resp.status_code == 202
    body = resp.json()
    await collect_sse_events(client, body["run_id"])
    return body["conversation_id"]


async def test_list_conversations(monkeypatch):
    patch_model_resolution(monkeypatch, output_text="hello there")
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
    patch_model_resolution(monkeypatch, output_text="hello there")
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
    patch_model_resolution(monkeypatch, output_text="hello there")
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
    patch_model_resolution(monkeypatch, output_text="hello there")
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


def _artifact_view(artifact_id: str) -> ArtifactView:
    return ArtifactView(
        id=artifact_id,
        conversation_id="conv-1",
        title="Chart",
        filename="chart.png",
        content_type="image/png",
        kind="image",
        size=3,
        created_at=datetime.now(UTC),
    )


def test_cold_read_reattaches_published_artifact():
    # A successful publish_artifact call on a turn re-attaches its artifact when
    # the conversation is read cold (warm/cold parity).
    art = _artifact_view("a1b2c3")
    tool = ToolView(
        id="t1",
        name="preview_publish_artifact",
        args={},
        status="ok",
        result=format_publish_result(art),
    )
    message = MessageView(role="assistant", tools=[tool])
    refs = _message_artifacts(message, {art.id: art})
    assert [r.artifact_id for r in refs] == ["a1b2c3"]
    assert refs[0].kind == "image"


def test_cold_read_skips_failed_publish():
    # A degraded/failed publish carries no id, so nothing is attached.
    tool = ToolView(
        id="t1",
        name="preview_publish_artifact",
        args={},
        status="ok",
        result="Could not read 'x.html': no such file",
    )
    message = MessageView(role="assistant", tools=[tool])
    assert _message_artifacts(message, {}) == []
