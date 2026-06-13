"""Search provider REST surface: CRUD, write-only API key, 404s."""

from __future__ import annotations

from ._helpers import client_app


async def test_provider_crud_over_http():
    async with client_app() as (client, _app):
        assert (await client.get("/search/providers")).json() == []

        created = await client.post(
            "/search/providers",
            json={
                "name": "local-searx",
                "base_url": "http://searx.local",
                "engines": ["google", "duckduckgo"],
                "params": {"language": "en"},
                "api_key": "s3cret",
            },
        )
        assert created.status_code == 201
        body = created.json()
        provider_id = body["id"]
        assert body["name"] == "local-searx"
        assert body["engines"] == ["google", "duckduckgo"]
        assert body["params"] == {"language": "en"}
        # The API key is write-only — never echoed, only its presence is reported.
        assert "api_key" not in body
        assert body["has_api_key"] is True

        patched = await client.patch(
            f"/search/providers/{provider_id}", json={"enabled": False}
        )
        assert patched.status_code == 200
        assert patched.json()["enabled"] is False

        assert (await client.get(f"/search/providers/{provider_id}")).json()["enabled"] is False

        deleted = await client.delete(f"/search/providers/{provider_id}")
        assert deleted.status_code == 204
        assert (await client.get("/search/providers")).json() == []


async def test_provider_unknown_id_404():
    async with client_app() as (client, _app):
        assert (await client.get("/search/providers/nope")).status_code == 404
        assert (await client.patch("/search/providers/nope", json={})).status_code == 404
        assert (await client.delete("/search/providers/nope")).status_code == 404
