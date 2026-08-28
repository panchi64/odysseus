"""The View history keeper bookmark (`POST /views/snapshots/{id}/keeper`): set/unset,
reflected in the conversation detail's snapshot refs, 404 on an unknown or unowned
snapshot."""

from __future__ import annotations

from pathlib import Path

from core.db import init_db, make_engine
from core.vault import Vault
from services.workspace_history import WorkspaceHistoryStore

from ._helpers import client_app, collect_sse_events, patch_model_resolution


async def _start_conversation(client) -> str:
    resp = await client.post("/chat", json={"prompt": "hi"})
    body = resp.json()
    await collect_sse_events(client, body["run_id"])
    return body["conversation_id"]


async def test_set_keeper_204_and_reflected_in_conversation_detail(monkeypatch):
    patch_model_resolution(monkeypatch, output_text="hi")
    async with client_app() as (client, app):
        conv = await _start_conversation(client)
        snap = await app.state.workspace_history.capture(
            "operator", conv, run_id="r1", files={"a.py": b"x"}
        )
        # Not yet a keeper.
        detail = (await client.get(f"/conversations/{conv}")).json()
        assert detail["snapshots"][0]["keeper"] is False

        resp = await client.post(f"/views/snapshots/{snap.id}/keeper", json={"keeper": True})
        assert resp.status_code == 204

        detail = (await client.get(f"/conversations/{conv}")).json()
        assert detail["snapshots"][0]["keeper"] is True


async def test_unset_keeper(monkeypatch):
    patch_model_resolution(monkeypatch, output_text="hi")
    async with client_app() as (client, app):
        conv = await _start_conversation(client)
        snap = await app.state.workspace_history.capture(
            "operator", conv, run_id="r1", files={"a.py": b"x"}
        )
        await client.post(f"/views/snapshots/{snap.id}/keeper", json={"keeper": True})

        resp = await client.post(f"/views/snapshots/{snap.id}/keeper", json={"keeper": False})
        assert resp.status_code == 204

        detail = (await client.get(f"/conversations/{conv}")).json()
        assert detail["snapshots"][0]["keeper"] is False


async def test_keeper_unknown_snapshot_404():
    async with client_app() as (client, _app):
        resp = await client.post("/views/snapshots/nope/keeper", json={"keeper": True})
        assert resp.status_code == 404


async def test_keeper_wrong_owner_404(tmp_path: Path):
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    vault = Vault(tmp_path / "keyfile.json")
    await vault.setup("pw")
    store = WorkspaceHistoryStore(engine, vault)
    snap = await store.capture("owner-a", "conv-1", run_id="r1", files={"a.py": b"x"})

    assert await store.set_keeper("owner-b", snap.id, True) is False
