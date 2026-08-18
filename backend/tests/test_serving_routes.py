"""The local-serving route surface — recommendations and status.

Hardware detection is stubbed to an Apple-Silicon profile so the assertions don't
depend on the test host.
"""

from __future__ import annotations

import asyncio
import sys

from services.cookbook.models import (
    Accelerator,
    AcceleratorKind,
    ComputeBackend,
    HardwareProfile,
    MemoryInfo,
    PlatformInfo,
)
from services.serving.adapters.llamacpp import LlamaCppAdapter
from services.serving.adapters.mlx import MlxAdapter
from services.serving.download import DownloadSpec
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


async def test_recommendations_and_status(monkeypatch):
    async def fake_detect(self) -> HardwareProfile:
        return _apple_profile()

    monkeypatch.setattr("services.cookbook.service.CookbookService.detect", fake_detect)

    async with client_app() as (client, _app):
        recs = await client.get("/models/serving/recommendations")
        assert recs.status_code == 200
        body = recs.json()
        assert body[0]["engine"] == "mlx" and body[0]["available"] is True
        assert any(r["engine"] == "llama.cpp" and r["available"] for r in body)

        models = await client.get("/models/serving/models")
        assert models.status_code == 200 and models.json() == []


async def test_download_flow_creates_and_completes_a_managed_model(monkeypatch):
    # Downloads run in a child process, so swap the llama.cpp download spec for a stub
    # child that writes an artifact and reports it — no network/HF, no cross-process
    # monkeypatch needed.
    stub = (
        "import sys\n"
        "from pathlib import Path\n"
        "d = Path(sys.argv[1]); d.mkdir(parents=True, exist_ok=True)\n"
        "(d / 'model.gguf').write_bytes(b'0123456789')\n"
        "print('ARTIFACT ' + str(d / 'model.gguf'), flush=True)\n"
    )

    def fake_spec(self, repo, quant, dest, token=None):
        return DownloadSpec(argv=[sys.executable, "-c", stub, str(dest)])

    monkeypatch.setattr(LlamaCppAdapter, "download_spec", fake_spec)

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


async def test_serve_unavailable_engine_returns_409(monkeypatch):
    # Force MLX unavailable so the test is host-independent (it's genuinely available on
    # an Apple-Silicon dev host) and exercises only the unavailable→409 mapping (a host
    # precondition, not an upstream failure) — without kicking off a real install/serve.
    async def unavailable(self) -> bool:
        return False

    monkeypatch.setattr(MlxAdapter, "is_available", unavailable)
    async with client_app() as (client, _app):
        resp = await client.post(
            "/models/serving/serve", json={"engine": "mlx", "repo": "mlx-community/whatever"}
        )
        assert resp.status_code == 409


async def test_stop_unknown_model_returns_404():
    async with client_app() as (client, _app):
        resp = await client.post("/models/serving/does-not-exist/stop")
        assert resp.status_code == 404


async def test_serve_rejects_an_extra_arg_the_platform_owns():
    # The operator's typo is a 400 the form can render, not a spawn that fails minutes
    # later — and --host in particular would move the server off loopback. Validation
    # runs before anything is downloaded or spawned, so no engine work happens here.
    async with client_app() as (client, _app):
        resp = await client.post(
            "/models/serving/serve",
            json={
                "engine": "llama.cpp",
                "repo": "acme/model-GGUF",
                "options": {"extra_args": ["--host", "0.0.0.0"]},
            },
        )
        assert resp.status_code == 400
        assert "--host" in resp.json()["detail"]


async def test_serve_rejects_options_for_an_engine_that_ignores_them(monkeypatch):
    # MLX's adapter discards LaunchOptions; accepting them would persist tuning that
    # never reaches a process while the UI shows it as applied.
    async def unavailable(self) -> bool:
        return False

    monkeypatch.setattr(MlxAdapter, "is_available", unavailable)
    async with client_app() as (client, _app):
        resp = await client.post(
            "/models/serving/serve",
            json={
                "engine": "mlx",
                "repo": "mlx-community/whatever",
                "options": {"context_size": 4096},
            },
        )
        # 400, not the 409 an unavailable engine earns — validation runs first.
        assert resp.status_code == 400
        assert "no tunable launch options" in resp.json()["detail"]


async def test_serve_options_persist_onto_the_managed_model(monkeypatch):
    def fake_spec(self, repo, quant, dest, token=None):
        return DownloadSpec(argv=[sys.executable, "-c", "pass"])

    monkeypatch.setattr(LlamaCppAdapter, "download_spec", fake_spec)

    async with client_app() as (client, _app):
        resp = await client.post(
            "/models/serving/serve",
            json={
                "engine": "llama.cpp",
                "repo": "acme/model-GGUF",
                "options": {"context_size": 16384, "kv_cache_type": "q8_0"},
            },
        )
        assert resp.status_code == 200
        assert resp.json()["options"]["context_size"] == 16384

        # And they survive into the status listing, so the form can show what was set.
        listing = (await client.get("/models/serving/models")).json()
        row = next(m for m in listing if m["hf_repo"] == "acme/model-GGUF")
        assert row["options"]["kv_cache_type"] == "q8_0"
