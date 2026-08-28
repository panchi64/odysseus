"""The backup REST surface (`BACKUP-1..2`): export, re-import, and what it reports."""

from __future__ import annotations

from tests._helpers import client_app

SECRET = "correct horse battery staple"


async def _memory(client, content: str) -> None:
    resp = await client.post("/memory", json={"content": content})
    assert resp.status_code == 201


async def test_manifest_is_null_until_the_first_export():
    async with client_app() as (client, _):
        assert (await client.get("/backup/manifest")).json() is None

        exported = await client.post("/backup/export", json={"secret": SECRET})
        assert exported.status_code == 200

        manifest = (await client.get("/backup/manifest")).json()
        assert manifest["createdAt"] == exported.json()["manifest"]["createdAt"]


async def test_contents_reports_the_discovered_groups():
    async with client_app() as (client, _):
        await _memory(client, "Deploys go out on Thursdays")

        contents = (await client.get("/backup/contents")).json()
        assert {"memories", "skills", "settings", "preferences"} <= set(contents["sections"])
        assert dict((i["name"], i["count"]) for i in contents["items"])["memories"] == 1


async def test_export_then_reimport_is_idempotent():
    async with client_app() as (client, _):
        await _memory(client, "Deploys go out on Thursdays")
        envelope = (await client.post("/backup/export", json={"secret": SECRET})).json()[
            "envelope"
        ]
        assert "Thursdays" not in str(envelope)

        first = await client.post(
            "/backup/import", json={"secret": SECRET, "envelope": envelope}
        )
        # The rows are already here — a restore onto its own source adds nothing.
        assert first.json()["imported"]["memories"] == 0
        assert first.json()["skipped"]["memories"] == 1
        assert len((await client.get("/memory")).json()) == 1


async def test_a_wrong_secret_is_400_not_an_auth_failure():
    async with client_app() as (client, _):
        await _memory(client, "A fact")
        envelope = (await client.post("/backup/export", json={"secret": SECRET})).json()[
            "envelope"
        ]

        # 400, deliberately: 401/423 would have the frontend client drop the session and
        # bounce to login over a mistyped recovery passphrase.
        wrong = await client.post(
            "/backup/import", json={"secret": "nope", "envelope": envelope}
        )
        assert wrong.status_code == 400


async def test_a_file_that_is_not_a_backup_is_422():
    async with client_app() as (client, _):
        resp = await client.post(
            "/backup/import", json={"secret": SECRET, "envelope": {"hello": "world"}}
        )
        assert resp.status_code == 422


async def test_export_requires_a_secret():
    async with client_app() as (client, _):
        assert (await client.post("/backup/export", json={"secret": ""})).status_code == 422
