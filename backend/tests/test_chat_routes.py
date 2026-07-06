"""POST /chat creates a Run that streams over the substrate SSE surface."""

from __future__ import annotations

from core.config import get_settings

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


async def test_ephemeral_chat_is_not_titled(monkeypatch):
    # Ephemeral (compare) threads are hidden from the listing and show no title, so
    # auto-titling them is invisible work that only holds the run open after the
    # answer — the route disables it. A normal first turn is still named.
    patch_model_resolution(monkeypatch)

    async with client_app() as (client, _app):
        eph = await client.post("/chat", json={"prompt": "hi", "ephemeral": True})
        eph_events = await collect_sse_events(client, eph.json()["run_id"])

        normal = await client.post("/chat", json={"prompt": "hi"})
        normal_events = await collect_sse_events(client, normal.json()["run_id"])

    assert not any(e["type"] == "conversation.titled" for e in eph_events)
    assert any(e["type"] == "conversation.titled" for e in normal_events)


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


async def test_chat_settings_round_trip():
    # The attachment inline token cap is an operator setting: GET reports the config
    # default until set, PUT overrides it, and the override persists.
    async with client_app() as (client, _app):
        got = await client.get("/chat/settings")
        assert got.status_code == 200
        default = get_settings().attachment_inline_max_tokens
        assert got.json()["attachment_inline_max_tokens"] == default

        put = await client.put("/chat/settings", json={"attachment_inline_max_tokens": 1500})
        assert put.status_code == 200
        assert put.json()["attachment_inline_max_tokens"] == 1500

        again = await client.get("/chat/settings")
        assert again.json()["attachment_inline_max_tokens"] == 1500


async def test_chat_settings_rejects_a_negative_cap():
    async with client_app() as (client, _app):
        resp = await client.put("/chat/settings", json={"attachment_inline_max_tokens": -1})
        assert resp.status_code == 422


async def test_chat_settings_rejects_an_unknown_field():
    # With every field optional (omitted ⇒ unchanged), a mistyped key must 422 rather than
    # silently no-op with a 200 — otherwise a client believes a write landed that never did.
    async with client_app() as (client, _app):
        resp = await client.put(
            "/chat/settings", json={"attachment_inline_max_token": 1500}  # typo: missing 's'
        )
        assert resp.status_code == 422


async def test_compaction_settings_round_trip():
    # The compaction preferences are operator settings: GET reports the config defaults,
    # PUT overrides them, and the override persists.
    async with client_app() as (client, _app):
        cfg = get_settings()
        got = (await client.get("/chat/settings")).json()
        assert got["compaction_enabled"] == cfg.compaction_enabled
        assert got["compaction_keep_recent"] == cfg.compaction_keep_recent

        put = await client.put(
            "/chat/settings",
            json={
                "attachment_inline_max_tokens": got["attachment_inline_max_tokens"],
                "compaction_enabled": False,
                "compaction_keep_recent": 3,
                "compaction_min_tokens": 2000,
            },
        )
        assert put.status_code == 200
        body = put.json()
        assert body["compaction_enabled"] is False
        assert body["compaction_keep_recent"] == 3
        assert body["compaction_min_tokens"] == 2000

        again = (await client.get("/chat/settings")).json()
        assert again["compaction_enabled"] is False and again["compaction_keep_recent"] == 3


async def test_compaction_settings_partial_update_leaves_others_unchanged():
    # Tuning only the attachment cap must not reset compaction overrides set earlier.
    async with client_app() as (client, _app):
        await client.put(
            "/chat/settings",
            json={"attachment_inline_max_tokens": 100, "compaction_keep_recent": 9},
        )
        await client.put("/chat/settings", json={"attachment_inline_max_tokens": 200})
        again = (await client.get("/chat/settings")).json()
        assert again["compaction_keep_recent"] == 9  # preserved across the attachment-only PUT
        assert again["attachment_inline_max_tokens"] == 200
