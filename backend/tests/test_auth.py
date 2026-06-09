"""Auth: first-run setup, login, the global gate, lock, and dual transport."""

from __future__ import annotations

from ._helpers import client_app


async def test_setup_then_access_then_lock_cycle():
    async with client_app(auth_enabled=True, passphrase=None) as (client, _app):
        # Fresh: not initialized, and feature endpoints are gated.
        status = (await client.get("/auth/status")).json()
        assert status == {"initialized": False, "unlocked": False, "auth_enabled": True}
        assert (await client.get("/runs/whatever")).status_code == 401

        # First-run setup chooses the password and returns a session.
        setup = await client.post("/setup", json={"password": "correct horse"})
        assert setup.status_code == 200
        assert setup.json()["token"]

        # The cookie now authorizes feature endpoints (404 = reached the handler).
        assert (await client.get("/runs/whatever")).status_code == 404
        assert (await client.get("/auth/status")).json()["unlocked"] is True

        # Lock wipes the key and revokes sessions → gated again.
        assert (await client.post("/auth/lock")).status_code == 200
        assert (await client.get("/runs/whatever")).status_code == 401


async def test_setup_is_one_time_and_password_min_length():
    async with client_app(auth_enabled=True, passphrase=None) as (client, _app):
        assert (await client.post("/setup", json={"password": "short"})).status_code == 422
        assert (await client.post("/setup", json={"password": "long enough"})).status_code == 200
        # already set up
        assert (await client.post("/setup", json={"password": "long enough"})).status_code == 409


async def test_login_rejects_wrong_password_and_accepts_right():
    async with client_app(auth_enabled=True, passphrase=None) as (client, _app):
        await client.post("/setup", json={"password": "the-password"})
        await client.post("/auth/lock")

        assert (await client.post("/auth/login", json={"password": "nope"})).status_code == 401
        ok = await client.post("/auth/login", json={"password": "the-password"})
        assert ok.status_code == 200
        assert (await client.get("/runs/whatever")).status_code == 404


async def test_bearer_token_authorizes_without_cookie():
    async with client_app(auth_enabled=True, passphrase=None) as (client, _app):
        token = (await client.post("/setup", json={"password": "the-password"})).json()["token"]
        client.cookies.clear()  # drop the cookie; rely on the bearer token

        assert (await client.get("/runs/whatever")).status_code == 401
        headers = {"Authorization": f"Bearer {token}"}
        assert (await client.get("/runs/whatever", headers=headers)).status_code == 404


async def test_auth_disabled_still_requires_unlock():
    # auth off + a passphrase ⇒ unlocked at boot, no token needed.
    async with client_app(auth_enabled=False, passphrase="dev-pass") as (client, _app):
        assert (await client.get("/runs/whatever")).status_code == 404
        # locking still blocks until re-unlocked, even with auth off.
        await client.post("/auth/lock")
        assert (await client.get("/runs/whatever")).status_code == 423
