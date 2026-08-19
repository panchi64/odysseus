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


async def test_serve_rejects_a_field_the_engine_cannot_translate(monkeypatch):
    # mlx-vlm's prefix cache is automatic, so it has no minimum-reuse knob. Accepting the
    # field would persist tuning that never reaches a process while the UI shows it as
    # applied — and the refusal names the field, so the form can point at it.
    async def unavailable(self) -> bool:
        return False

    monkeypatch.setattr(MlxAdapter, "is_available", unavailable)
    async with client_app() as (client, _app):
        resp = await client.post(
            "/models/serving/serve",
            json={
                "engine": "mlx",
                "repo": "mlx-community/whatever",
                "options": {"cache_reuse": 256},
            },
        )
        # 400, not the 409 an unavailable engine earns — validation runs first.
        assert resp.status_code == 400
        assert "cache_reuse" in resp.json()["detail"]


async def test_serve_accepts_a_field_the_engine_does_translate(monkeypatch):
    # The counterpart: context size reaches mlx-vlm as --max-kv-size, so it must not be
    # refused. The engine is unavailable here, so the request gets that far and stops at
    # the 409 — which is exactly the proof that validation let it through.
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
        assert resp.status_code == 409


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


# --- importing a model already on disk --------------------------------------


def _gguf(tmp_path) -> str:
    path = tmp_path / "Qwen3-8B-Q4_K_M.gguf"
    path.write_bytes(b"GGUF")
    return str(path)


async def test_import_registers_a_model_already_on_disk(tmp_path):
    async with client_app() as (client, _app):
        resp = await client.post(
            "/models/serving/import",
            json={"engine": "llama.cpp", "path": _gguf(tmp_path)},
        )
        assert resp.status_code == 201
        body = resp.json()
        # Ready to serve with nothing to fetch, and pointed at the operator's own file.
        assert body["state"] == "stopped"
        assert body["source"] == "local"
        assert body["artifact_path"] == _gguf(tmp_path)
        assert body["hf_repo"] == "Qwen3-8B-Q4_K_M"


async def test_import_takes_a_display_name(tmp_path):
    async with client_app() as (client, _app):
        resp = await client.post(
            "/models/serving/import",
            json={"engine": "llama.cpp", "path": _gguf(tmp_path), "name": "My Qwen"},
        )
        assert resp.json()["hf_repo"] == "My Qwen"


async def test_import_refuses_a_path_that_is_not_there(tmp_path):
    async with client_app() as (client, _app):
        resp = await client.post(
            "/models/serving/import",
            json={"engine": "llama.cpp", "path": str(tmp_path / "nowhere.gguf")},
        )
        assert resp.status_code == 400
        assert "nothing at" in resp.json()["detail"]


async def test_import_refuses_the_wrong_shape_for_the_engine(tmp_path):
    # A folder is what MLX wants and llama.cpp doesn't — the rejection says which.
    (tmp_path / "snapshot").mkdir()
    async with client_app() as (client, _app):
        resp = await client.post(
            "/models/serving/import",
            json={"engine": "llama.cpp", "path": str(tmp_path / "snapshot")},
        )
        assert resp.status_code == 400
        assert ".gguf" in resp.json()["detail"]


async def test_import_refuses_a_relative_path(tmp_path):
    async with client_app() as (client, _app):
        resp = await client.post(
            "/models/serving/import",
            json={"engine": "llama.cpp", "path": "models/thing.gguf"},
        )
        assert resp.status_code == 400
        assert "full path" in resp.json()["detail"]


async def test_import_refuses_an_engine_this_host_cannot_run(monkeypatch, tmp_path):
    async def unavailable(self) -> bool:
        return False

    monkeypatch.setattr(MlxAdapter, "is_available", unavailable)
    (tmp_path / "snap").mkdir()
    async with client_app() as (client, _app):
        resp = await client.post(
            "/models/serving/import",
            json={"engine": "mlx", "path": str(tmp_path / "snap")},
        )
        assert resp.status_code == 409


# --- the native file chooser ------------------------------------------------


async def test_file_picker_availability_is_reported_either_way(monkeypatch):
    # The UI only shows a BROWSE control when this says yes; the path field works
    # regardless, so an unavailable chooser is a clean answer, never an error.
    monkeypatch.setattr("services.host_picker._resolve", lambda: None)
    async with client_app() as (client, _app):
        body = (await client.get("/models/serving/file-picker")).json()
        assert body["available"] is False
        assert body["reason"]


async def test_opening_a_chooser_on_a_host_without_one_is_a_409(monkeypatch):
    monkeypatch.setattr("services.host_picker._resolve", lambda: None)
    async with client_app() as (client, _app):
        resp = await client.post(
            "/models/serving/file-picker", json={"mode": "directory"}
        )
        assert resp.status_code == 409


async def test_a_cancelled_chooser_returns_no_path(monkeypatch):
    async def cancelled(*args, **kwargs):
        return None

    monkeypatch.setattr("services.host_picker.pick", cancelled)
    async with client_app() as (client, _app):
        resp = await client.post("/models/serving/file-picker", json={"mode": "file"})
        assert resp.status_code == 200
        assert resp.json()["path"] is None
