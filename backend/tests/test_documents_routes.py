"""The /documents REST surface + its corpus enrollment, over a booted app."""

from __future__ import annotations

from ._helpers import client_app


async def test_document_crud_and_version_history():
    async with client_app() as (client, _app):
        # Create.
        created = await client.post("/documents", json={"title": "Notes", "body": "first"})
        assert created.status_code == 201
        doc = created.json()
        assert doc["title"] == "Notes" and doc["body"] == "first"
        assert doc["docType"] == "text" and doc["archived"] is False  # camelCase out
        doc_id = doc["id"]

        # List shows it.
        listed = (await client.get("/documents")).json()
        assert [d["id"] for d in listed] == [doc_id]

        # Edit appends a version.
        edited = await client.patch(f"/documents/{doc_id}", json={"body": "second"})
        assert edited.status_code == 200 and edited.json()["body"] == "second"

        versions = (await client.get(f"/documents/{doc_id}/versions")).json()
        assert [v["version"] for v in versions] == [2, 1]
        assert versions[1]["origin"] == "user"

        # Restore version 1.
        restored = await client.post(f"/documents/{doc_id}/versions/1/restore")
        assert restored.status_code == 200 and restored.json()["body"] == "first"


async def test_archive_restore_and_delete():
    async with client_app() as (client, _app):
        doc_id = (await client.post("/documents", json={"title": "T", "body": "b"})).json()["id"]

        await client.post(f"/documents/{doc_id}/archive")
        assert (await client.get("/documents")).json() == []
        assert (await client.get("/documents", params={"include_archived": True})).json()

        await client.post(f"/documents/{doc_id}/restore")
        assert len((await client.get("/documents")).json()) == 1

        assert (await client.delete(f"/documents/{doc_id}")).status_code == 204
        assert (await client.get(f"/documents/{doc_id}")).status_code == 404


async def test_validation_and_not_found():
    async with client_app() as (client, _app):
        assert (await client.post("/documents", json={"title": "  "})).status_code == 422
        assert (await client.get("/documents/nope")).status_code == 404
        assert (await client.patch("/documents/nope", json={"body": "x"})).status_code == 404
        assert (await client.post("/documents/nope/archive")).status_code == 404


async def test_documents_surface_is_real_not_a_stub():
    async with client_app() as (client, _app):
        await client.post("/documents", json={"title": "T", "body": "a note about a cat"})
        sources = (await client.get("/corpus/sources")).json()
        row = next(s for s in sources if s["id"] == "surf-documents")
        # No longer a stub: the real adapter reports it as an indexed surface.
        assert row["kind"] == "surface"
        assert row["status"] == "indexed"
        assert row["href"] == "/documents"
