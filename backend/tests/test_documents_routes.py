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


# --- suggestion review (`DOC-3`) --------------------------------------------


async def _propose(app, doc_id: str, changes, summary: str = ""):
    """Seed a suggestion set through the store — the agent's `document_suggest` is the
    only producer, so the REST surface is review-only and has no create route."""
    from services.document_suggestions import ProposedChange

    return await app.state.documents.suggestions.propose(
        "operator",
        doc_id,
        [ProposedChange(*c) for c in changes],
        summary=summary,
    )


async def test_suggestions_are_reviewable_change_by_change():
    async with client_app() as (client, app):
        doc_id = (
            await client.post("/documents", json={"title": "Notes", "body": "alpha\nbeta\n"})
        ).json()["id"]
        proposed = await _propose(
            app,
            doc_id,
            [("alpha", "ALPHA", "louder"), ("beta", "BETA", "")],
            summary="shout it",
        )

        listed = (await client.get(f"/documents/{doc_id}/suggestions")).json()
        assert len(listed) == 1
        assert listed[0]["summary"] == "shout it" and listed[0]["pending"] == 2
        assert listed[0]["changes"][0]["oldText"] == "alpha"  # camelCase out
        assert listed[0]["changes"][0]["explanation"] == "louder"
        assert listed[0]["changes"][0]["status"] == "pending"

        # Accepting one applies exactly that change and mints one version.
        accept = await client.post(
            f"/documents/{doc_id}/suggestion-changes/{proposed.changes[0].id}/accept"
        )
        assert accept.status_code == 200
        applied = accept.json()
        assert applied["version"] == 2
        assert applied["document"]["body"] == "ALPHA\nbeta\n"
        assert applied["accepted"] == [proposed.changes[0].id] and applied["skipped"] == []

        # Rejecting the other writes no version at all.
        reject = await client.post(
            f"/documents/{doc_id}/suggestion-changes/{proposed.changes[1].id}/reject"
        )
        assert reject.status_code == 204
        assert (await client.get(f"/documents/{doc_id}")).json()["body"] == "ALPHA\nbeta\n"
        versions = (await client.get(f"/documents/{doc_id}/versions")).json()
        assert [v["version"] for v in versions] == [2, 1]

        # A fully reviewed set drops out of the pending list but stays inspectable.
        assert (await client.get(f"/documents/{doc_id}/suggestions")).json() == []
        resolved = (
            await client.get(f"/documents/{doc_id}/suggestions", params={"include_resolved": True})
        ).json()
        assert [c["status"] for c in resolved[0]["changes"]] == ["accepted", "rejected"]
        assert resolved[0]["changes"][0]["version"] == 2
        assert resolved[0]["changes"][1]["version"] is None


async def test_accept_all_applies_a_whole_set_as_one_version():
    async with client_app() as (client, app):
        doc_id = (
            await client.post("/documents", json={"title": "Notes", "body": "one two three"})
        ).json()["id"]
        proposed = await _propose(app, doc_id, [("one", "1"), ("two", "2"), ("three", "3")])

        applied = (
            await client.post(f"/documents/{doc_id}/suggestions/{proposed.id}/accept-all")
        ).json()

        assert applied["document"]["body"] == "1 2 3"
        assert applied["version"] == 2 and len(applied["accepted"]) == 3
        versions = (await client.get(f"/documents/{doc_id}/versions")).json()
        assert [v["version"] for v in versions] == [2, 1]
        assert (await client.get(f"/documents/{doc_id}/suggestions")).json() == []


async def test_accepting_a_stale_suggestion_is_a_conflict_not_a_corruption():
    async with client_app() as (client, app):
        doc_id = (
            await client.post("/documents", json={"title": "Notes", "body": "alpha\nbeta\n"})
        ).json()["id"]
        proposed = await _propose(app, doc_id, [("alpha", "ALPHA")])

        # The operator rewrites the span the suggestion was anchored to.
        await client.patch(f"/documents/{doc_id}", json={"body": "rewritten\nbeta\n"})

        conflict = await client.post(
            f"/documents/{doc_id}/suggestion-changes/{proposed.changes[0].id}/accept"
        )
        assert conflict.status_code == 409
        assert (await client.get(f"/documents/{doc_id}")).json()["body"] == "rewritten\nbeta\n"
        # Refusing is not deciding — the change is still there to review.
        assert (await client.get(f"/documents/{doc_id}/suggestions")).json()[0]["pending"] == 1


async def test_suggestion_review_not_found_paths():
    async with client_app() as (client, app):
        doc_id = (await client.post("/documents", json={"title": "Notes", "body": "alpha"})).json()[
            "id"
        ]
        other_id = (
            await client.post("/documents", json={"title": "Other", "body": "alpha"})
        ).json()["id"]
        proposed = await _propose(app, doc_id, [("alpha", "ALPHA")])
        change_id = proposed.changes[0].id

        assert (await client.get("/documents/nope/suggestions")).status_code == 404
        assert (
            await client.post(f"/documents/{doc_id}/suggestion-changes/nope/accept")
        ).status_code == 404
        assert (
            await client.post(f"/documents/{doc_id}/suggestions/nope/accept-all")
        ).status_code == 404
        # The nested path is honest: a change reached through the wrong document is a 404.
        assert (
            await client.post(f"/documents/{other_id}/suggestion-changes/{change_id}/accept")
        ).status_code == 404
        assert (
            await client.post(f"/documents/{other_id}/suggestions/{proposed.id}/accept-all")
        ).status_code == 404

        # Deciding twice is never a second decision.
        assert (
            await client.post(f"/documents/{doc_id}/suggestion-changes/{change_id}/reject")
        ).status_code == 204
        assert (
            await client.post(f"/documents/{doc_id}/suggestion-changes/{change_id}/accept")
        ).status_code == 404
