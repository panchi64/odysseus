"""The document-version keeper bookmark (`POST /documents/{id}/versions/{v}/keeper`):
set/unset, reflected in the version listing and the conversation detail's document
refs, 404 on an unknown document/version or an unowned one."""

from __future__ import annotations

from ._helpers import client_app, collect_sse_events, patch_model_resolution


async def _start_conversation(client) -> str:
    resp = await client.post("/chat", json={"prompt": "hi"})
    body = resp.json()
    await collect_sse_events(client, body["run_id"])
    return body["conversation_id"]


async def test_set_keeper_204_and_reflected_in_version_listing():
    async with client_app() as (client, _app):
        doc_id = (await client.post("/documents", json={"title": "T", "body": "b"})).json()["id"]

        versions = (await client.get(f"/documents/{doc_id}/versions")).json()
        assert versions[0]["keeper"] is False

        resp = await client.post(f"/documents/{doc_id}/versions/1/keeper", json={"keeper": True})
        assert resp.status_code == 204

        versions = (await client.get(f"/documents/{doc_id}/versions")).json()
        assert versions[0]["keeper"] is True


async def test_unset_keeper():
    async with client_app() as (client, _app):
        doc_id = (await client.post("/documents", json={"title": "T", "body": "b"})).json()["id"]
        await client.post(f"/documents/{doc_id}/versions/1/keeper", json={"keeper": True})

        resp = await client.post(f"/documents/{doc_id}/versions/1/keeper", json={"keeper": False})
        assert resp.status_code == 204

        versions = (await client.get(f"/documents/{doc_id}/versions")).json()
        assert versions[0]["keeper"] is False


async def test_keeper_reflected_in_conversation_detail(monkeypatch):
    patch_model_resolution(monkeypatch, output_text="hi")
    async with client_app() as (client, app):
        conv = await _start_conversation(client)
        doc = await app.state.documents.create("operator", "Notes", "body", conversation_id=conv)

        detail = (await client.get(f"/conversations/{conv}")).json()
        [doc_ref] = detail["documents"]
        assert doc_ref["versions"][0]["keeper"] is False

        await client.post(f"/documents/{doc.id}/versions/1/keeper", json={"keeper": True})

        detail = (await client.get(f"/conversations/{conv}")).json()
        assert detail["documents"][0]["versions"][0]["keeper"] is True


async def test_keeper_unknown_document_or_version_404():
    async with client_app() as (client, _app):
        assert (
            await client.post("/documents/nope/versions/1/keeper", json={"keeper": True})
        ).status_code == 404

        doc_id = (await client.post("/documents", json={"title": "T", "body": "b"})).json()["id"]
        assert (
            await client.post(f"/documents/{doc_id}/versions/99/keeper", json={"keeper": True})
        ).status_code == 404


async def test_keeper_wrong_owner_404():
    from .test_documents_service import _store

    _engine, _vault, _chunks, adapter, store = await _store()
    doc = await store.create("owner-a", "Notes", "body")
    await adapter.stop()

    assert await store.set_keeper("owner-b", doc.id, 1, True) is False
