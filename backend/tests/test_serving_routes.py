"""The local-serving route surface — recommendations, catalog, and status.

Hardware detection is stubbed to an Apple-Silicon profile so the assertions don't
depend on the test host.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from services.cookbook.models import (
    Accelerator,
    AcceleratorKind,
    ComputeBackend,
    HardwareProfile,
    MemoryInfo,
    PlatformInfo,
)
from services.serving.adapters.mlx import MlxAdapter
from tests._helpers import client_app

_GB = 1024**3


def _apple_profile() -> HardwareProfile:
    return HardwareProfile(
        memory=MemoryInfo(total_bytes=128 * _GB, available_bytes=100 * _GB),
        accelerators=[
            Accelerator(
                name="Apple M3 Max", kind=AcceleratorKind.metal,
                vram_bytes=96 * _GB, unified=True,
            )
        ],
        compute_backend=ComputeBackend.metal,
        platform=PlatformInfo(system="Darwin", release="24", arch="arm64"),
    )


async def test_recommendations_catalog_and_status(monkeypatch):
    async def fake_detect(self) -> HardwareProfile:
        return _apple_profile()

    monkeypatch.setattr("services.cookbook.service.CookbookService.detect", fake_detect)

    async with client_app() as (client, _app):
        recs = await client.get("/models/serving/recommendations")
        assert recs.status_code == 200
        body = recs.json()
        assert body[0]["engine"] == "mlx" and body[0]["available"] is True
        assert any(r["engine"] == "llama.cpp" and r["available"] for r in body)

        catalog = await client.get(
            "/models/serving/catalog", params={"engine": "llama.cpp", "workload": "chat"}
        )
        assert catalog.status_code == 200
        entries = catalog.json()
        assert entries and all(e["engine"] == "llama.cpp" for e in entries)

        embed = await client.get(
            "/models/serving/catalog", params={"engine": "llama.cpp", "workload": "embedding"}
        )
        assert embed.status_code == 200
        assert all(e["workload"] == "embedding" for e in embed.json())

        models = await client.get("/models/serving/models")
        assert models.status_code == 200 and models.json() == []


async def test_download_flow_creates_and_completes_a_managed_model(monkeypatch):
    # Stub the HuggingFace seam so no network/download happens — the fake fetch just
    # writes a file into the destination the manager hands it.
    monkeypatch.setattr(
        "services.serving.hf.gguf_filename", lambda repo, quant: "model.q4_k_m.gguf"
    )
    monkeypatch.setattr("services.serving.hf.file_size", lambda repo, filename: 10)

    def fake_fetch_file(repo: str, filename: str, dest: Path) -> Path:
        dest.mkdir(parents=True, exist_ok=True)
        target = dest / filename
        target.write_bytes(b"0123456789")
        return target

    monkeypatch.setattr("services.serving.hf.fetch_file", fake_fetch_file)

    async with client_app() as (client, _app):
        resp = await client.post(
            "/models/serving/download",
            json={"engine": "llama.cpp", "repo": "acme/model-GGUF", "quant": "q4_k_m"},
        )
        assert resp.status_code == 202
        row = resp.json()
        managed_id = row["id"]
        assert row["state"] in {"downloading", "stopped"}

        # Poll status until the background download settles.
        final = None
        for _ in range(200):
            listing = (await client.get("/models/serving/models")).json()
            final = next((m for m in listing if m["id"] == managed_id), None)
            if final and final["state"] == "stopped":
                break
            await asyncio.sleep(0.02)

        assert final is not None and final["state"] == "stopped"
        assert final["hf_repo"] == "acme/model-GGUF" and final["quant"] == "q4_k_m"


async def test_serve_unavailable_engine_returns_502(monkeypatch):
    # Force MLX unavailable so the test is host-independent (it's genuinely available on
    # an Apple-Silicon dev host) and exercises only the unavailable→502 mapping — without
    # kicking off a real engine install/serve in the background.
    async def unavailable(self) -> bool:
        return False

    monkeypatch.setattr(MlxAdapter, "is_available", unavailable)
    async with client_app() as (client, _app):
        resp = await client.post(
            "/models/serving/serve", json={"engine": "mlx", "repo": "mlx-community/whatever"}
        )
        assert resp.status_code == 502


async def test_stop_unknown_model_returns_404():
    async with client_app() as (client, _app):
        resp = await client.post("/models/serving/does-not-exist/stop")
        assert resp.status_code == 404
