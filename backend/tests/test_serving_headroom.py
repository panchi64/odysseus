"""The pre-flight headroom guard — serve refuses a model that won't fit alongside
what's already resident, and names the models to stop.

The guard sizes the candidate via the engine adapter (here a stub returning fixed
footprints — no network) and sums the resident models from their on-disk artifacts, so
the test writes small real artifacts and sets the VRAM budget relative to two known sizes
to force (and then clear) the out-of-memory case.
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
from services.serving.supervisor import ProcessSupervisor

OWNER = "operator"
RESIDENT_REPO = "acme/Resident-GGUF"
NEW_REPO = "acme/New-GGUF"
RESIDENT_BYTES = 50
NEW_BYTES = 60
# usable_budget applies a 0.9 fit-fraction, so a 120-byte VRAM budget leaves 108 usable:
# the 60-byte candidate fits alone, but not beside the 50-byte resident (110 > 108).
TIGHT_VRAM = 120


class _SizingAdapter(FakeAdapter):
    """A FakeAdapter that sizes a known set of repos without touching the network, so the
    headroom math is deterministic. An unknown repo sizes to ``None`` (degrade → allow)."""

    _SIZES = {RESIDENT_REPO: RESIDENT_BYTES, NEW_REPO: NEW_BYTES}

    def download_size(self, repo: str, quant: str | None, token: str | None = None) -> int | None:
        return self._SIZES.get(repo)


def _profile(vram_bytes: int) -> HardwareProfile:
    return HardwareProfile(
        memory=MemoryInfo(total_bytes=vram_bytes, available_bytes=vram_bytes),
        accelerators=[
            Accelerator(
                name="Test GPU",
                kind=AcceleratorKind.metal,
                vram_bytes=vram_bytes,
                unified=True,
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
        adapters={EngineKind.llama_cpp: _SizingAdapter()},
        supervisor=ProcessSupervisor(startup_timeout_s=15.0, poll_interval_s=0.1),
    )
    return service, registry


async def _seed_resident(service: ServingService, tmp_path: Path, repo: str, nbytes: int) -> None:
    """Mark a model as already running (no real process) with a real on-disk artifact of
    ``nbytes`` bytes, so the guard sums its true footprint."""
    row = await service._store.get_or_create(
        OWNER, EngineKind.llama_cpp, repo, Workload.chat, "q4_k_m"
    )
    artifact = tmp_path / f"{row.id}.gguf"
    artifact.write_bytes(b"x" * nbytes)
    await service._store.update(
        row.id, state=ServeState.running, port=51000, artifact_path=str(artifact)
    )


async def test_serve_refused_when_a_resident_model_leaves_no_room(tmp_path: Path):
    # The budget fits either model alone, but not both — serving the second must refuse.
    service, _registry = await _service(tmp_path, TIGHT_VRAM)
    try:
        await _seed_resident(service, tmp_path, RESIDENT_REPO, RESIDENT_BYTES)
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
        await _seed_resident(service, tmp_path, RESIDENT_REPO, RESIDENT_BYTES)
        started = await service.serve(OWNER, EngineKind.llama_cpp, NEW_REPO, quant="q4_k_m")
        # The guard let it through; it then serves normally.
        view = None
        for _ in range(400):
            view = next((m for m in await service.status(OWNER) if m.id == started.id), None)
            if view and view.state in (ServeState.running, ServeState.error):
                break
            await asyncio.sleep(0.05)
        assert view is not None and view.state == ServeState.running
    finally:
        await service.shutdown()


async def test_unsizable_repo_skips_the_guard(tmp_path: Path):
    # A repo the adapter can't size (HF unreachable / private) must not block — degrade
    # toward allowing even at an absurdly small budget.
    service, _registry = await _service(tmp_path, 1)
    try:
        await _seed_resident(service, tmp_path, RESIDENT_REPO, RESIDENT_BYTES)
        started = await service.serve(OWNER, EngineKind.llama_cpp, "acme/Unsized-GGUF")
        assert started.id  # no ServingError raised
    finally:
        await service.shutdown()
