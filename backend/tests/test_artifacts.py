"""The artifact store and its REST surface: capture/serve round-trip, encryption
at rest, conversation scoping, and the sandboxing headers on served content."""

from __future__ import annotations

import pytest

from core.db import init_db, make_engine
from core.exceptions import NotFoundError
from core.vault import Vault
from services.artifacts import ArtifactStore, guess_content_type

from ._helpers import client_app


async def _store(tmp_path) -> ArtifactStore:
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    vault = Vault(tmp_path / "keyfile.json")
    await vault.setup("pw")
    return ArtifactStore(engine, vault)


# --- content-type + kind inference -------------------------------------------
def test_guess_content_type_and_kind():
    assert guess_content_type("report.html") == "text/html"
    assert guess_content_type("chart.png") == "image/png"
    assert guess_content_type("notes") == "text/plain"  # unknown → text


# --- store round-trip --------------------------------------------------------
async def test_publish_then_serve_round_trip(tmp_path):
    store = await _store(tmp_path)
    view = await store.publish(
        "operator", "conv-1", filename="report.html", content=b"<h1>hi</h1>", title="Report"
    )
    assert view.kind == "html"
    assert view.content_type == "text/html"
    assert view.size == 11

    blob = await store.content("operator", view.id)
    assert blob.content == b"<h1>hi</h1>"
    assert blob.content_type == "text/html"


async def test_content_is_encrypted_at_rest(tmp_path):
    from sqlmodel import Session, select

    from models.artifact import Artifact

    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    vault = Vault(tmp_path / "k.json")
    await vault.setup("pw")
    store = ArtifactStore(engine, vault)

    view = await store.publish("operator", "conv-1", filename="s.txt", content=b"SECRET-XYZ")
    with Session(engine) as session:
        row = session.exec(select(Artifact).where(Artifact.id == view.id)).one()
    assert b"SECRET-XYZ" not in row.blob_enc  # raw bytes on disk are ciphertext


async def test_list_is_scoped_to_owner_and_conversation(tmp_path):
    store = await _store(tmp_path)
    await store.publish("operator", "conv-1", filename="a.txt", content=b"a")
    await store.publish("operator", "conv-1", filename="b.png", content=b"\x89PNG")
    await store.publish("operator", "conv-2", filename="c.txt", content=b"c")

    items = await store.list("operator", "conv-1")
    assert [i.filename for i in items] == ["a.txt", "b.png"]
    assert await store.list("other", "conv-1") == []


async def test_get_unknown_or_foreign_artifact_raises(tmp_path):
    store = await _store(tmp_path)
    view = await store.publish("operator", "conv-1", filename="a.txt", content=b"a")
    with pytest.raises(NotFoundError):
        await store.get("operator", "no-such-id")
    with pytest.raises(NotFoundError):
        await store.get("intruder", view.id)  # owner mismatch reads as not-found


# --- REST surface ------------------------------------------------------------
async def test_content_route_serves_inert_with_sandbox_headers():
    async with client_app() as (client, app):
        view = await app.state.artifacts.publish(
            "operator", "conv-1", filename="r.html", content=b"<b>x</b>", title="R"
        )
        resp = await client.get(f"/artifacts/{view.id}/content")
        assert resp.status_code == 200
        assert resp.content == b"<b>x</b>"
        assert resp.headers["content-type"].startswith("text/html")
        assert "sandbox" in resp.headers["content-security-policy"]
        assert resp.headers["x-content-type-options"] == "nosniff"


async def test_list_and_get_routes():
    async with client_app() as (client, app):
        view = await app.state.artifacts.publish(
            "operator", "conv-1", filename="r.html", content=b"<b>x</b>", title="R"
        )
        listing = await client.get("/artifacts", params={"conversation_id": "conv-1"})
        assert listing.status_code == 200
        assert [a["filename"] for a in listing.json()] == ["r.html"]

        one = await client.get(f"/artifacts/{view.id}")
        assert one.json()["title"] == "R"
        assert (await client.get("/artifacts/nope")).status_code == 404
