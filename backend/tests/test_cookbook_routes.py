"""Cookbook routes — shape + degrade, over a booted app.

The background catalog warm-up is stubbed out (no network at boot); compatible-model
tests inject a fixed catalog by patching `ModelCatalog.get`. Hardware comes from the
real (local, side-effect-free) probe.
"""

from __future__ import annotations

from core.exceptions import DegradedCapabilityError
from services.cookbook.catalog import ModelCatalog
from services.cookbook.models import Capabilities, CatalogModel, QuantVariant
from services.cookbook.service import CookbookService
from tests._helpers import client_app

_GIB = 1024**3
_FIXED_CATALOG = [
    CatalogModel(
        id="Qwen/Qwen2.5-7B-Instruct",
        name="Qwen2.5-7B-Instruct",
        params_b=7.62,
        context_default=131072,
        capabilities=Capabilities(tools=True),
        quants=[QuantVariant(label="Q4_K_M", bits_per_weight=4.5, size_bytes=4 * _GIB)],
    )
]


async def _no_warmup(self):  # keep boot off the network
    return None


async def test_hardware_route_returns_a_profile(monkeypatch):
    monkeypatch.setattr(CookbookService, "warmup", _no_warmup)
    async with client_app() as (client, _app):
        resp = await client.get("/models/cookbook/hardware")
        assert resp.status_code == 200
        body = resp.json()
        assert {"cpu", "memory", "platform", "compute_backend", "runtimes"} <= body.keys()


async def test_compatible_route(monkeypatch):
    monkeypatch.setattr(CookbookService, "warmup", _no_warmup)

    async def fixed_get(self):
        return _FIXED_CATALOG

    monkeypatch.setattr(ModelCatalog, "get", fixed_get)
    async with client_app() as (client, _app):
        resp = await client.get("/models/cookbook/compatible")
        assert resp.status_code == 200
        body = resp.json()
        assert body["available"] is True
        assert any(m["model_id"] == "Qwen/Qwen2.5-7B-Instruct" for m in body["models"])


async def test_search_route(monkeypatch):
    monkeypatch.setattr(CookbookService, "warmup", _no_warmup)

    async def fake_search(self, query):
        assert query == "qwen"
        return _FIXED_CATALOG

    monkeypatch.setattr(ModelCatalog, "search", fake_search)
    async with client_app() as (client, _app):
        # An empty query short-circuits to an empty list without hitting the catalog.
        empty = await client.get("/models/cookbook/search?q=")
        assert empty.status_code == 200 and empty.json() == {"models": [], "available": True}
        # A real query returns models scored against the detected hardware.
        resp = await client.get("/models/cookbook/search?q=qwen")
        assert resp.status_code == 200
        assert any(m["model_id"] == "Qwen/Qwen2.5-7B-Instruct" for m in resp.json()["models"])


async def test_simulated_compatible_post(monkeypatch):
    monkeypatch.setattr(CookbookService, "warmup", _no_warmup)

    async def fixed_get(self):
        return _FIXED_CATALOG

    monkeypatch.setattr(ModelCatalog, "get", fixed_get)
    async with client_app() as (client, _app):
        # A synthetic, low-memory CPU host — the what-if path.
        profile = {
            "platform": {"system": "Linux", "release": "6.0", "arch": "x86_64"},
            "memory": {"total_bytes": 8 * _GIB},
            "compute_backend": "cpu",
        }
        resp = await client.post("/models/cookbook/compatible", json=profile)
        assert resp.status_code == 200
        assert resp.json()["available"] is True


async def test_compatible_degrades_to_empty(monkeypatch):
    monkeypatch.setattr(CookbookService, "warmup", _no_warmup)

    async def boom(self):
        raise DegradedCapabilityError("catalog unavailable")

    monkeypatch.setattr(ModelCatalog, "get", boom)
    async with client_app() as (client, _app):
        resp = await client.get("/models/cookbook/compatible")
        assert resp.status_code == 200
        assert resp.json() == {"models": [], "available": False}


async def test_quality_source_get_set_and_key_status(monkeypatch):
    monkeypatch.setattr(CookbookService, "warmup", _no_warmup)
    async with client_app() as (client, _app):
        # Default is keyless LMArena; the keyed sources have no key yet.
        body = (await client.get("/models/cookbook/quality-source")).json()
        assert body["active"] == "lmarena"
        opts = {o["id"]: o for o in body["options"]}
        assert set(opts) == {"lmarena", "artificial_analysis", "llm_stats"}
        assert opts["lmarena"]["has_key"] is True
        assert opts["artificial_analysis"]["requires_key"] is True
        assert opts["artificial_analysis"]["has_key"] is False

        # Switching the source persists and is reflected on the next read.
        resp = await client.put(
            "/models/cookbook/quality-source", json={"source": "artificial_analysis"}
        )
        assert resp.status_code == 200 and resp.json()["active"] == "artificial_analysis"
        again = await client.get("/models/cookbook/quality-source")
        assert again.json()["active"] == "artificial_analysis"

        # An unknown source is rejected.
        bad = await client.put("/models/cookbook/quality-source", json={"source": "bogus"})
        assert bad.status_code == 422

        # Setting that source's API token flips its has_key.
        await client.put("/credentials/artificial_analysis", json={"api_key": "sk-x"})
        opts = {
            o["id"]: o
            for o in (await client.get("/models/cookbook/quality-source")).json()["options"]
        }
        assert opts["artificial_analysis"]["has_key"] is True
