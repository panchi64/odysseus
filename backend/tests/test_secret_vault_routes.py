"""The secrets-manager REST surface (`VAULT-1`): setup, unlock, lock, and entry CRUD."""

from __future__ import annotations

from tests._helpers import client_app

PASSPHRASE = "vault-passphrase"


async def _unlocked(client):
    resp = await client.post("/vault/configure", json={"passphrase": PASSPHRASE})
    assert resp.status_code == 201


async def test_state_walks_unconfigured_to_unlocked():
    async with client_app() as (client, _):
        state = (await client.get("/vault/state")).json()
        assert state == {"configured": False, "unlocked": False}

        await _unlocked(client)
        assert (await client.get("/vault/state")).json() == {
            "configured": True,
            "unlocked": True,
        }

        # Configuring twice would strand every stored entry behind a discarded key.
        second = await client.post("/vault/configure", json={"passphrase": "other"})
        assert second.status_code == 409


async def test_lock_then_unlock_round_trip():
    async with client_app() as (client, _):
        await _unlocked(client)

        assert (await client.post("/vault/lock")).json()["unlocked"] is False
        assert (await client.post("/vault/unlock", json={"passphrase": "wrong"})).status_code == 403
        assert (await client.post("/vault/unlock", json={"passphrase": PASSPHRASE})).json()[
            "unlocked"
        ] is True

        # Logout is the broader teardown — same observable state, different scope.
        assert (await client.post("/vault/logout")).json()["unlocked"] is False


async def test_unlock_before_configure_is_a_precondition_failure():
    async with client_app() as (client, _):
        resp = await client.post("/vault/unlock", json={"passphrase": PASSPHRASE})
        assert resp.status_code == 409


async def test_entry_crud():
    async with client_app() as (client, _):
        await _unlocked(client)

        created = await client.post(
            "/vault/entries",
            json={
                "name": "Production DB",
                "username": "admin",
                "url": "db://prod",
                "password": "s3cret",
            },
        )
        assert created.status_code == 201
        entry = created.json()
        assert entry["name"] == "Production DB" and entry["password"] == "s3cret"

        listed = (await client.get("/vault/entries")).json()
        assert [e["id"] for e in listed] == [entry["id"]]

        patched = await client.patch(f"/vault/entries/{entry['id']}", json={"password": "rotated"})
        assert patched.json()["password"] == "rotated"
        assert patched.json()["name"] == "Production DB"

        assert (await client.delete(f"/vault/entries/{entry['id']}")).status_code == 204
        assert (await client.get("/vault/entries")).json() == []


async def test_locked_vault_answers_409_everywhere():
    async with client_app() as (client, _):
        await _unlocked(client)
        entry_id = (
            await client.post("/vault/entries", json={"name": "db", "password": "pw"})
        ).json()["id"]
        await client.post("/vault/lock")

        assert (await client.get("/vault/entries")).status_code == 409
        assert (await client.post("/vault/entries", json={"name": "x"})).status_code == 409
        assert (
            await client.patch(f"/vault/entries/{entry_id}", json={"password": "x"})
        ).status_code == 409
        assert (await client.delete(f"/vault/entries/{entry_id}")).status_code == 409


async def test_unknown_entry_is_404():
    async with client_app() as (client, _):
        await _unlocked(client)
        assert (await client.delete("/vault/entries/nope")).status_code == 404
        assert (
            await client.patch("/vault/entries/nope", json={"password": "x"})
        ).status_code == 404


async def test_the_service_is_one_singleton_across_requests():
    async with client_app() as (client, app):
        await _unlocked(client)
        first = app.state.secret_vault
        await client.get("/vault/entries")
        # A per-request instance would have thrown the unlock away between the two calls.
        assert app.state.secret_vault is first
