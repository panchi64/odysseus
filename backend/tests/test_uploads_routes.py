"""The /uploads REST surface + its corpus enrollment, over a booted app.

The booted app wires the built-in extractor (no MinerU on the CI host, no vision
endpoint configured), so these exercise the text/native-PDF paths — enough to cover
the HTTP surface end to end."""

from __future__ import annotations

from core.ratelimit import RateLimiter

from ._helpers import client_app
from .test_uploads_extraction import text_pdf


async def _await_extraction(app):
    await app.state.uploads._worker.join()
    await app.state.corpus_uploads._worker.join()


async def test_upload_extract_list_download_correct_delete():
    async with client_app() as (client, app):
        created = await client.post(
            "/uploads", files={"file": ("notes.txt", b"zebra knowledge here", "text/plain")}
        )
        assert created.status_code == 201
        up = created.json()
        uid = up["id"]
        assert up["filename"] == "notes.txt" and up["sizeBytes"] == 20  # camelCase out

        await _await_extraction(app)

        detail = (await client.get(f"/uploads/{uid}")).json()
        assert detail["status"] == "done"
        assert detail["extractedText"] == "zebra knowledge here"
        assert detail["extractor"] == "basic"

        listed = (await client.get("/uploads")).json()
        assert [u["id"] for u in listed] == [uid] and listed[0]["hasText"] is True

        content = await client.get(f"/uploads/{uid}/content")
        assert content.content == b"zebra knowledge here"
        assert "attachment" in content.headers["content-disposition"]

        corrected = await client.patch(f"/uploads/{uid}", json={"text": "fixed text"})
        assert corrected.status_code == 200 and corrected.json()["extractedText"] == "fixed text"

        assert (await client.delete(f"/uploads/{uid}")).status_code == 204
        assert (await client.get(f"/uploads/{uid}")).status_code == 404


async def test_pdf_text_extracted_via_route():
    async with client_app() as (client, app):
        created = await client.post(
            "/uploads", files={"file": ("doc.pdf", text_pdf("route pdf marker"), "application/pdf")}
        )
        uid = created.json()["id"]
        await _await_extraction(app)
        assert "route pdf marker" in (await client.get(f"/uploads/{uid}")).json()["extractedText"]


async def test_duplicate_returns_200():
    async with client_app() as (client, _app):
        first = await client.post("/uploads", files={"file": ("a.txt", b"same", "text/plain")})
        second = await client.post("/uploads", files={"file": ("a.txt", b"same", "text/plain")})
        assert first.status_code == 201 and second.status_code == 200
        assert first.json()["id"] == second.json()["id"]


async def test_empty_file_rejected():
    async with client_app() as (client, _app):
        resp = await client.post("/uploads", files={"file": ("e.txt", b"", "text/plain")})
        assert resp.status_code == 422


async def test_rate_limited_returns_429():
    async with client_app() as (client, app):
        # A 1-token bucket that never refills ⇒ the second upload is throttled.
        app.state.upload_rate_limiter = RateLimiter(rate_per_second=0.0, burst=1)
        ok = await client.post("/uploads", files={"file": ("a.txt", b"one", "text/plain")})
        throttled = await client.post("/uploads", files={"file": ("b.txt", b"two", "text/plain")})
        assert ok.status_code == 201 and throttled.status_code == 429
        assert "retry-after" in throttled.headers


async def test_uploads_surface_is_real_not_a_stub():
    async with client_app() as (client, _app):
        sources = (await client.get("/corpus/sources")).json()
        row = next(s for s in sources if s["id"] == "surf-uploads")
        assert row["kind"] == "surface"
        assert row["status"] == "indexed"
        assert row["href"] == "/uploads"
