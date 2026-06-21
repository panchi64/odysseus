"""Cookbook routes — host hardware shape, over a booted app.

The background warm-up is stubbed out (no probe at boot); the hardware route returns the
real (local, side-effect-free) probe.
"""

from __future__ import annotations

from services.cookbook.service import CookbookService
from tests._helpers import client_app


async def _no_warmup(self):  # keep boot off the host probe
    return None


async def test_hardware_route_returns_a_profile(monkeypatch):
    monkeypatch.setattr(CookbookService, "warmup", _no_warmup)
    async with client_app() as (client, _app):
        resp = await client.get("/models/cookbook/hardware")
        assert resp.status_code == 200
        body = resp.json()
        assert {"cpu", "memory", "platform", "compute_backend", "runtimes"} <= body.keys()
