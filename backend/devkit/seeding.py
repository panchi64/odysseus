"""Running the fixture pack against a live instance.

Separate from :mod:`devkit.seed` so that the pack stays a set of fixtures and this stays
the one place that knows how to reach an instance — which client, which base URL, whether
a login is needed. A fixture should be three lines against a route; everything else that
seeding involves is here.

Synchronous on the outside, because the launcher is: ``up`` is a sequence of steps and
one of them happens to be asynchronous inside.
"""

from __future__ import annotations

import asyncio

import httpx

from devkit.instance import DevInstance
from devkit.seed import SeedContext, run_seed, seed_version

#: Long enough for the seeded conversations, which run real turns through the engine.
_TIMEOUT_S = 300.0


def version() -> str:
    """The current fixture pack's version — what a workspace is compared against."""
    return seed_version()


async def _authenticated(instance: DevInstance) -> httpx.AsyncClient:
    """A client that can write to this instance.

    With auth off there is nothing to do: the gate is not in the request path at all.
    With auth on the vault is already unlocked by the boot passphrase, so logging in is
    just asking for the session token — it does not decide whether the workspace opens.
    """
    client = httpx.AsyncClient(base_url=instance.backend_url, timeout=_TIMEOUT_S)
    if instance.auth:
        response = await client.post("/auth/login", json={"password": instance.password})
        response.raise_for_status()
        client.headers["Authorization"] = f"Bearer {response.json()['token']}"
    return client


async def _run(instance: DevInstance) -> list[str]:
    client = await _authenticated(instance)
    async with client:
        return await run_seed(SeedContext(client=client, instance=instance))


def seed(instance: DevInstance) -> list[str]:
    """Seed the instance, returning one summary line per fixture."""
    return asyncio.run(_run(instance))
