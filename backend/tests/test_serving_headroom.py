"""The pre-flight headroom guard — serve refuses a model that won't fit alongside
what's already resident, and names the models to stop.

The catalog footprints are deterministic, so the test sets the VRAM budget relative to
two known catalog models to force (and then clear) the out-of-memory case.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from core.db import init_db, make_engine
from core.exceptions import ServingError
from core.vault import Vault
from services.cookbook import CookbookService
from services.cookbook.models import (
    Accelerator,
    AcceleratorKind,
    ComputeBackend,
    HardwareProfile,
    MemoryInfo,
    PlatformInfo,
)
from services.registry import ModelRegistry
from services.serving import EngineKind, ServeState, ServingPaths, ServingService, Workload
from services.serving.adapters.fake import FakeAdapter
from services.serving.catalog import CATALOG
from services.serving.supervisor import ProcessSupervisor

OWNER = "operator"

# Two catalog llama.cpp chat models with known footprints.
RESIDENT_REPO = "Qwen/Qwen2.5-7B-Instruct-GGUF"
NEW_REPO = "Qwen/Qwen2.5-14B-Instruct-GGUF"


def _catalog_bytes(repo: str) -> int:
    return next(e.approx_bytes for e in CATALOG if e.repo == repo and e.approx_bytes)


def _profile(vram_bytes: int) -> HardwareProfile:
    return HardwareProfile(
        memory=MemoryInfo(total_bytes=vram_bytes, available_bytes=vram_bytes),
        accelerators=[
            Accelerator(
                name="Test GPU", kind=AcceleratorKind.metal,
                vram_bytes=vram_bytes, unified=True,
            )
        ],
        compute_backend=ComputeBackend.metal,
        platform=PlatformInfo(system="Darwin", release="24", arch="arm64"),
    )


async def _service(tmp_path: Path, vram_bytes: int) -> tuple[ServingService, ModelRegistry]:
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    vault = Vault(tmp_path / "keyfile.json")
    await vault.setup("test-passphrase")
    registry = ModelRegistry(engine, vault)
    cookbook = CookbookService()

    async def fake_detect() -> HardwareProfile:
        return _profile(vram_bytes)

    cookbook.detect = fake_detect  # type: ignore[method-assign]
    service = ServingService(
        engine,
        vault,
        registry,
        cookbook,
        ServingPaths(tmp_path),
        adapters={EngineKind.llama_cpp: FakeAdapter()},
        supervisor=ProcessSupervisor(startup_timeout_s=15.0, poll_interval_s=0.1),
    )
    return service, registry


async def _seed_resident(service: ServingService, repo: str) -> None:
    """Mark a model as already running (no real process) so it counts against memory."""
    row = await service._store.get_or_create(
        OWNER, EngineKind.llama_cpp, repo, Workload.chat, "q4_k_m"
    )
    await service._store.update(row.id, state=ServeState.running, port=51000)


async def test_serve_refused_when_a_resident_model_leaves_no_room(tmp_path: Path):
    # Budget fits either model alone, but not both — serving the second must refuse.
    budget = _catalog_bytes(RESIDENT_REPO) + _catalog_bytes(NEW_REPO)
    service, _registry = await _service(tmp_path, budget)
    try:
        await _seed_resident(service, RESIDENT_REPO)
        with pytest.raises(ServingError) as exc:
            await service.serve(OWNER, EngineKind.llama_cpp, NEW_REPO, quant="q4_k_m")
        # The message names the model to stop and never created a row for the refused one.
        assert RESIDENT_REPO in str(exc.value)
        assert all(m.hf_repo != NEW_REPO for m in await service.status(OWNER))
    finally:
        await service.shutdown()


async def test_serve_allowed_with_ample_budget(tmp_path: Path):
    service, _registry = await _service(tmp_path, 256 * 1024**3)
    try:
        await _seed_resident(service, RESIDENT_REPO)
        started = await service.serve(OWNER, EngineKind.llama_cpp, NEW_REPO, quant="q4_k_m")
        # The guard let it through; it then serves normally.
        view = None
        for _ in range(400):
            view = next(
                (m for m in await service.status(OWNER) if m.id == started.id), None
            )
            if view and view.state in (ServeState.running, ServeState.error):
                break
            await asyncio.sleep(0.05)
        assert view is not None and view.state == ServeState.running
    finally:
        await service.shutdown()


async def test_free_text_repo_skips_the_guard(tmp_path: Path):
    # A repo not in the catalog can't be sized pre-download, so the guard must not block.
    service, _registry = await _service(tmp_path, 1)  # an absurdly small budget
    try:
        await _seed_resident(service, RESIDENT_REPO)
        started = await service.serve(OWNER, EngineKind.llama_cpp, "acme/Unsized-GGUF")
        assert started.id  # no ServingError raised
    finally:
        await service.shutdown()
