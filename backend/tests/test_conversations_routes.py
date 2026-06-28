"""The conversations REST surface — list, read (projected history), rename, delete.

A conversation comes into being as a side effect of a chat turn, so each test
drives ``POST /chat`` (against a TestModel) to create one, then exercises the
read/manage endpoints over it.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from routes.conversations import _message_versions
from services.conversation_view import MessageView, ToolView
from services.workspace_history import SnapshotView, format_show_result

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
        assert row["model"] == "test"  # the model the turn ran on (TestModel)


async def test_summary_model_survives_a_cold_read(monkeypatch):
    """The last-used model is durable: it's recovered from the stored response blob
    after the in-memory tree is evicted, not only while the conversation is warm."""
    patch_model_resolution(monkeypatch, output_text="hello there")
    async with client_app() as (client, app):
        conversation_id = await _start_conversation(client)
        app.state.conversations._cache.clear()  # force the cold (DB) summary path

        store = app.state.conversations
        await store._worker.join()  # let the write-behind drainer settle the model
        store._cache.clear()  # force the cold (DB) summary path

        rows = (await client.get("/conversations")).json()
        assert rows[0]["id"] == conversation_id
        assert rows[0]["model"] == "test"


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
        assert messages[0]["model"] is None  # user turns carry no model
        assert messages[1]["content"] == "hello there"
        assert messages[1]["tools"] == []
        assert messages[1]["model"] == "test"  # the assistant turn's model


async def test_get_unknown_conversation_404():
    async with client_app() as (client, _app):
        resp = await client.get("/conversations/does-not-exist")
        assert resp.status_code == 404


async def test_detail_reports_an_in_flight_run(monkeypatch):
    """A turn still streaming server-side surfaces as ``active_run`` on the cold
    read, so a reattaching client (e.g. a page reload mid-stream) can resume it
    instead of rendering the thread reply-less."""
    patch_model_resolution(monkeypatch, output_text="hello there")
    async with client_app() as (client, app):
        conversation_id = await _start_conversation(client)

        # The completed turn left no live run.
        first = (await client.get(f"/conversations/{conversation_id}")).json()
        assert first["active_run"] is None

        # Simulate a fresh turn that's still running for this conversation.
        started, release = asyncio.Event(), asyncio.Event()

        async def orch(run):
            started.set()
            await release.wait()

        run = app.state.runs.submit(
            kind="chat",
            owner_id="operator",
            orchestrator=orch,
            conversation_id=conversation_id,
        )
        await started.wait()

        detail = (await client.get(f"/conversations/{conversation_id}")).json()
        assert detail["active_run"]["id"] == run.id
        assert detail["active_run"]["status"] == "running"
        assert isinstance(detail["active_run"]["last_seq"], int)

        release.set()
        await run.wait()

        # Terminal again → the read no longer advertises a live run.
        after = (await client.get(f"/conversations/{conversation_id}")).json()
        assert after["active_run"] is None


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


async def test_retitle_overwrites_even_an_operator_title(monkeypatch):
    # A manual re-title is a deliberate operator action, so unlike the fill-only-if-blank
    # auto-titler it overwrites unconditionally — even a name the operator just set.
    patch_model_resolution(monkeypatch, output_text="Regenerated Name")
    async with client_app() as (client, _app):
        conversation_id = await _start_conversation(client)
        await client.patch(
            f"/conversations/{conversation_id}", json={"title": "Operator Name"}
        )

        resp = await client.post(f"/conversations/{conversation_id}/retitle")
        assert resp.status_code == 200
        assert resp.json()["title"] == "Regenerated Name"

        detail = await client.get(f"/conversations/{conversation_id}")
        assert detail.json()["title"] == "Regenerated Name"


async def test_retitle_resolves_background_with_the_picker_override(monkeypatch):
    # The conversation persists no endpoint, so a manual re-title names the thread with
    # the operator's current pick (like a chat turn) — not a default role they may
    # never have bound. The picked endpoint/model is forwarded to background resolution
    # (utility → the picked main), which carries reasoning-off so a thinking title model
    # doesn't burn its output budget before emitting a title.
    patch_model_resolution(monkeypatch, output_text="Picked Title")
    async with client_app() as (client, _app):
        conversation_id = await _start_conversation(client)

        from services.registry import ModelRegistry

        seen: dict[str, str | None] = {}
        real_resolve = ModelRegistry.resolve_background

        async def spy(self, *, owner_id, override_endpoint_id=None, override_model=None):
            seen["endpoint_id"] = override_endpoint_id
            seen["model"] = override_model
            return await real_resolve(
                self,
                owner_id=owner_id,
                override_endpoint_id=override_endpoint_id,
                override_model=override_model,
            )

        monkeypatch.setattr(ModelRegistry, "resolve_background", spy)

        resp = await client.post(
            f"/conversations/{conversation_id}/retitle",
            json={"endpoint_id": "ep-1", "model": "qwen3"},
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Picked Title"
        assert seen == {"endpoint_id": "ep-1", "model": "qwen3"}


async def test_retitle_unknown_conversation_404():
    async with client_app() as (client, _app):
        resp = await client.post("/conversations/nope/retitle")
        assert resp.status_code == 404


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


class _RecordingSandbox:
    """A stand-in for the sandbox manager that records purge calls (optionally failing)."""

    def __init__(self, *, fail: bool = False) -> None:
        self.purged: list[str] = []
        self._fail = fail

    async def purge(self, key: str) -> None:
        self.purged.append(key)
        if self._fail:
            raise RuntimeError("sandbox teardown blew up")


async def test_delete_conversation_purges_its_sandbox(monkeypatch):
    patch_model_resolution(monkeypatch, output_text="hi")
    async with client_app() as (client, app):
        conversation_id = await _start_conversation(client)
        app.state.sandbox = _RecordingSandbox()

        resp = await client.delete(f"/conversations/{conversation_id}")
        assert resp.status_code == 204
        assert app.state.sandbox.purged == [conversation_id]


async def test_delete_conversation_survives_a_failing_sandbox_purge(monkeypatch):
    patch_model_resolution(monkeypatch, output_text="hi")
    async with client_app() as (client, app):
        conversation_id = await _start_conversation(client)
        app.state.sandbox = _RecordingSandbox(fail=True)

        # The DB delete is authoritative; a best-effort purge failure must not fail it.
        resp = await client.delete(f"/conversations/{conversation_id}")
        assert resp.status_code == 204
        assert (await client.get(f"/conversations/{conversation_id}")).status_code == 404


def _snapshot_view(snapshot_id: str) -> SnapshotView:
    return SnapshotView(
        id=snapshot_id,
        conversation_id="conv-1",
        title="Chart",
        created_at=datetime.now(UTC),
        files_changed=1,
        summary="+1 ~0 -0",
        stats={"added": 1, "modified": 0, "removed": 0},
        preview_artifact_id="a1",
        preview_kind="image",
    )


def test_cold_read_reattaches_view_version():
    # A `show` on a turn re-attaches its version (an inline chip) when the conversation
    # is read cold: the tool result embeds the snapshot id, which keys the by-id map.
    snap = _snapshot_view("a1b2c3")
    tool = ToolView(
        id="t1",
        name="view_show",
        args={},
        status="ok",
        result=format_show_result(snap, "image"),
    )
    message = MessageView(role="assistant", tools=[tool])
    refs = _message_versions(message, {snap.id: snap})
    assert [r.snapshot_id for r in refs] == ["a1b2c3"]
    assert refs[0].preview_kind == "image"
    assert refs[0].title == "Chart"


def test_cold_read_skips_view_without_version_id():
    # A degraded capture (no id embedded) attaches nothing, even though the tool ran.
    tool = ToolView(
        id="t1",
        name="view_show",
        args={},
        status="ok",
        result="Could not read 'x.html': no such file",
    )
    message = MessageView(role="assistant", tools=[tool])
    assert _message_versions(message, {}) == []


async def test_compaction_override_round_trip(monkeypatch):
    patch_model_resolution(monkeypatch)
    async with client_app() as (client, _app):
        cid = await _start_conversation(client)

        # Defaults to null — the thread inherits the operator's global setting.
        got = await client.get(f"/conversations/{cid}/compaction")
        assert got.status_code == 200 and got.json()["override"] is None

        # Force compaction off for this thread; it persists.
        put = await client.put(f"/conversations/{cid}/compaction", json={"override": False})
        assert put.status_code == 200 and put.json()["override"] is False
        back = await client.get(f"/conversations/{cid}/compaction")
        assert back.json()["override"] is False

        # Clear it back to inherit.
        await client.put(f"/conversations/{cid}/compaction", json={"override": None})
        assert (await client.get(f"/conversations/{cid}/compaction")).json()["override"] is None


async def test_compaction_override_unknown_conversation_404(monkeypatch):
    patch_model_resolution(monkeypatch)
    async with client_app() as (client, _app):
        resp = await client.get("/conversations/does-not-exist/compaction")
        assert resp.status_code == 404
