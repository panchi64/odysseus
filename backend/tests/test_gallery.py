"""Gallery — the image lens over uploads, custom albums, and the keep/delete-image choice
woven into conversation deletes.

The gallery owns no image store: every image is an ``image/*`` upload, so these drive the
real ``/uploads`` + ``/gallery`` surfaces over a booted app. The orphan-purge safety check
is exercised both at the store level (the authoritative tree) and through the delete route.
"""

from __future__ import annotations

import hashlib
import io

from PIL import Image
from pydantic_ai import ModelRequest, UserPromptPart

from routes.deps import OPERATOR_ID

from ._helpers import client_app


def _png(name: str) -> bytes:
    """A tiny PNG whose pixel colour is derived from ``name`` — so distinct names yield
    distinct bytes (identical bytes would dedup to one upload under UP-1)."""
    seed = hashlib.sha256(name.encode()).digest()
    color = (seed[0], seed[1], seed[2])
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buf, format="PNG")
    return buf.getvalue()


async def _upload_image(client, name: str) -> str:
    resp = await client.post("/uploads", files={"file": (name, _png(name), "image/png")})
    assert resp.status_code in (200, 201)
    return resp.json()["id"]


def _user_turn(text: str = "look at this") -> ModelRequest:
    return ModelRequest(parts=[UserPromptPart(content=text)])


# --- the image lens ---------------------------------------------------------


async def test_media_lists_images_only_with_imported_bucket():
    async with client_app() as (client, _app):
        img = await _upload_image(client, "photo.png")
        await client.post("/uploads", files={"file": ("notes.txt", b"text", "text/plain")})

        media = (await client.get("/gallery/media")).json()
        assert [m["id"] for m in media] == [img]
        item = media[0]
        assert item["type"] == "image"
        assert item["title"] == "photo.png"
        # No chat references it ⇒ it sits in the "imported" provenance bucket.
        assert item["albumIds"] == ["sys-imported"]
        assert item["favorite"] is False and item["tags"] == []


async def test_favorite_toggles_through_uploads_and_shows_in_gallery():
    async with client_app() as (client, _app):
        img = await _upload_image(client, "fav.png")
        patched = await client.patch(f"/uploads/{img}", json={"favorite": True})
        assert patched.status_code == 200 and patched.json()["favorite"] is True

        media = (await client.get("/gallery/media")).json()
        assert media[0]["favorite"] is True

        await client.patch(f"/uploads/{img}", json={"favorite": False})
        assert (await client.get("/gallery/media")).json()[0]["favorite"] is False


# --- custom albums ----------------------------------------------------------


async def test_album_crud_and_membership():
    async with client_app() as (client, _app):
        a = await _upload_image(client, "a.png")
        b = await _upload_image(client, "b.png")

        created = await client.post("/gallery/albums", json={"name": "Trip"})
        assert created.status_code == 201
        album_id = created.json()["id"]
        assert created.json()["system"] is False

        albums = {row["id"]: row for row in (await client.get("/gallery/albums")).json()}
        assert albums["all"]["count"] == 2 and albums["all"]["system"] is True
        assert albums["sys-imported"]["count"] == 2 and albums["sys-chat"]["count"] == 0
        assert albums[album_id]["count"] == 0

        # Add one image, twice — the second add is idempotent, not a duplicate.
        items = f"/gallery/albums/{album_id}/items"
        assert (await client.post(items, json={"uploadId": a})).status_code == 204
        assert (await client.post(items, json={"uploadId": a})).status_code == 204
        albums = {row["id"]: row for row in (await client.get("/gallery/albums")).json()}
        assert albums[album_id]["count"] == 1

        media = {m["id"]: m for m in (await client.get("/gallery/media")).json()}
        assert album_id in media[a]["albumIds"] and album_id not in media[b]["albumIds"]

        renamed = await client.patch(f"/gallery/albums/{album_id}", json={"name": "Holiday"})
        assert renamed.status_code == 200 and renamed.json()["name"] == "Holiday"

        assert (await client.delete(f"/gallery/albums/{album_id}/items/{a}")).status_code == 204
        albums = {row["id"]: row for row in (await client.get("/gallery/albums")).json()}
        assert albums[album_id]["count"] == 0

        assert (await client.delete(f"/gallery/albums/{album_id}")).status_code == 204
        assert album_id not in {row["id"] for row in (await client.get("/gallery/albums")).json()}


async def test_system_albums_are_not_editable():
    async with client_app() as (client, _app):
        img = await _upload_image(client, "x.png")
        assert (await client.delete("/gallery/albums/all")).status_code == 404
        rename = await client.patch("/gallery/albums/sys-chat", json={"name": "no"})
        assert rename.status_code == 404
        add = await client.post("/gallery/albums/sys-imported/items", json={"uploadId": img})
        assert add.status_code == 404


async def test_album_name_required():
    async with client_app() as (client, _app):
        assert (await client.post("/gallery/albums", json={"name": "   "})).status_code == 422


async def test_deleting_image_cascades_album_membership():
    async with client_app() as (client, _app):
        img = await _upload_image(client, "doomed.png")
        album_id = (await client.post("/gallery/albums", json={"name": "Pinned"})).json()["id"]
        await client.post(f"/gallery/albums/{album_id}/items", json={"uploadId": img})
        assert (await client.delete(f"/uploads/{img}")).status_code == 204
        # The membership row is gone with the upload (FK cascade) ⇒ album back to empty.
        albums = {row["id"]: row for row in (await client.get("/gallery/albums")).json()}
        assert albums[album_id]["count"] == 0


# --- thumbnails -------------------------------------------------------------


async def test_thumbnail_serves_webp_and_revalidates():
    async with client_app() as (client, _app):
        img = await _upload_image(client, "thumb.png")
        first = await client.get(f"/uploads/{img}/thumbnail")
        assert first.status_code == 200
        assert first.headers["content-type"] == "image/webp"
        etag = first.headers["etag"]
        assert etag and "cache-control" in first.headers

        again = await client.get(f"/uploads/{img}/thumbnail", headers={"If-None-Match": etag})
        assert again.status_code == 304

        text = await client.post("/uploads", files={"file": ("n.txt", b"hi", "text/plain")})
        assert (await client.get(f"/uploads/{text.json()['id']}/thumbnail")).status_code == 415


async def test_content_forces_attachment_disposition():
    async with client_app() as (client, _app):
        img = await _upload_image(client, "inline.png")
        resp = await client.get(f"/uploads/{img}/content")
        # Always an attachment — operator-supplied bytes (e.g. an uploaded HTML/SVG) must
        # never render inline in the authenticated API origin.
        assert "attachment" in resp.headers["content-disposition"]


async def test_thumbnail_preserves_transparency():
    async with client_app() as (client, _app):
        buf = io.BytesIO()
        Image.new("RGBA", (8, 8), (255, 0, 0, 0)).save(buf, format="PNG")
        up = await client.post(
            "/uploads", files={"file": ("clear.png", buf.getvalue(), "image/png")}
        )
        resp = await client.get(f"/uploads/{up.json()['id']}/thumbnail")
        assert resp.status_code == 200 and resp.headers["content-type"] == "image/webp"
        # The alpha channel survives the WebP re-encode (the old RGB flatten would not).
        assert Image.open(io.BytesIO(resp.content)).mode == "RGBA"


async def test_remove_item_404s_on_unknown_album():
    async with client_app() as (client, _app):
        img = await _upload_image(client, "r.png")
        resp = await client.delete(f"/gallery/albums/does-not-exist/items/{img}")
        assert resp.status_code == 404


# --- gallery is not a corpus source -----------------------------------------


async def test_surf_gallery_not_a_corpus_source():
    async with client_app() as (client, _app):
        ids = {s["id"] for s in (await client.get("/corpus/sources")).json()}
        assert "surf-gallery" not in ids
        assert "surf-uploads" in ids  # gallery images are indexed here instead


# --- the delete-choice safety check -----------------------------------------


async def test_chat_attachment_shows_as_chat_bucket():
    async with client_app() as (client, app):
        img = await _upload_image(client, "chat.png")
        store = app.state.conversations
        cid = await store.create_conversation(OPERATOR_ID)
        store.record(cid, [_user_turn()], attachment_ids=[img], marker="[file]")

        item = (await client.get("/gallery/media")).json()[0]
        assert item["albumIds"] == ["sys-chat"]


async def test_orphan_check_spares_image_referenced_elsewhere():
    async with client_app() as (client, app):
        store = app.state.conversations
        shared = await _upload_image(client, "shared.png")
        only_c1 = await _upload_image(client, "only.png")

        c1 = await store.create_conversation(OPERATOR_ID)
        store.record(c1, [_user_turn()], attachment_ids=[shared, only_c1], marker="[f]")
        c2 = await store.create_conversation(OPERATOR_ID)
        store.record(c2, [_user_turn()], attachment_ids=[shared], marker="[f]")

        # Deleting c1 orphans only the image nothing else references.
        orphans = await store.orphaned_attachments_for_delete(OPERATOR_ID, c1, message_id=None)
        assert orphans == [only_c1]

        probe = await client.get(f"/conversations/{c1}/orphan-image-attachments")
        assert probe.json()["upload_ids"] == [only_c1]

        resp = await client.delete(f"/conversations/{c1}", params={"purgeImages": "true"})
        assert resp.status_code == 204
        assert (await client.get(f"/uploads/{only_c1}")).status_code == 404  # purged
        assert (await client.get(f"/uploads/{shared}")).status_code == 200  # kept (c2 uses it)


async def test_delete_keeps_images_by_default():
    async with client_app() as (client, app):
        store = app.state.conversations
        img = await _upload_image(client, "keep.png")
        cid = await store.create_conversation(OPERATOR_ID)
        store.record(cid, [_user_turn()], attachment_ids=[img], marker="[f]")

        assert (await client.delete(f"/conversations/{cid}")).status_code == 204
        assert (await client.get(f"/uploads/{img}")).status_code == 200


async def test_message_delete_purges_only_its_own_orphan():
    async with client_app() as (client, app):
        store = app.state.conversations
        first = await _upload_image(client, "first.png")
        second = await _upload_image(client, "second.png")
        cid = await store.create_conversation(OPERATOR_ID)
        store.record(cid, [_user_turn("one")], attachment_ids=[first], marker="[f]")
        store.record(cid, [_user_turn("two")], attachment_ids=[second], marker="[f]")

        tree = store._cache[cid]
        second_node = next(nid for nid, n in tree.nodes.items() if n.attachment_ids == [second])

        resp = await client.delete(
            f"/conversations/{cid}/messages/{second_node}", params={"purgeImages": "true"}
        )
        assert resp.status_code == 200
        # Only the deleted turn's image is purged; the surviving turn's image stays.
        assert (await client.get(f"/uploads/{second}")).status_code == 404
        assert (await client.get(f"/uploads/{first}")).status_code == 200


async def test_purge_spares_curated_image_in_album_or_favorited():
    async with client_app() as (client, app):
        store = app.state.conversations
        albumed = await _upload_image(client, "albumed.png")
        starred = await _upload_image(client, "starred.png")
        plain = await _upload_image(client, "plain.png")

        # Curate two of the three: one filed into an album, one favorited.
        album_id = (await client.post("/gallery/albums", json={"name": "Keep"})).json()["id"]
        await client.post(f"/gallery/albums/{album_id}/items", json={"uploadId": albumed})
        await client.patch(f"/uploads/{starred}", json={"favorite": True})

        cid = await store.create_conversation(OPERATOR_ID)
        store.record(
            cid, [_user_turn()], attachment_ids=[albumed, starred, plain], marker="[f]"
        )

        # Only the un-curated image is offered for purge…
        probe = await client.get(f"/conversations/{cid}/orphan-image-attachments")
        assert probe.json()["upload_ids"] == [plain]

        # …and choosing "delete images" leaves the curated ones untouched.
        resp = await client.delete(f"/conversations/{cid}", params={"purgeImages": "true"})
        assert resp.status_code == 204
        assert (await client.get(f"/uploads/{plain}")).status_code == 404  # purged
        assert (await client.get(f"/uploads/{albumed}")).status_code == 200  # kept (album)
        assert (await client.get(f"/uploads/{starred}")).status_code == 200  # kept (favorite)


async def test_deleting_upload_detaches_it_from_chat_message():
    async with client_app() as (client, app):
        store = app.state.conversations
        img = await _upload_image(client, "attached.png")
        keep = await _upload_image(client, "kept.png")
        cid = await store.create_conversation(OPERATOR_ID)
        store.record(cid, [_user_turn()], attachment_ids=[img, keep], marker="[f]")

        # Deleting the upload from the gallery drops its dangling id from the message.
        assert (await client.delete(f"/uploads/{img}")).status_code == 204
        detail = (await client.get(f"/conversations/{cid}")).json()
        attachments = detail["messages"][0]["attachment_ids"]
        assert img not in attachments and keep in attachments
