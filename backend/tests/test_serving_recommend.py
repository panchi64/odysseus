"""Engine recommendation — pure mapping from a hardware profile (no I/O)."""

from __future__ import annotations

from services.cookbook.models import (
    Accelerator,
    AcceleratorKind,
    ComputeBackend,
    HardwareProfile,
    MemoryInfo,
    PlatformInfo,
)
from services.serving import EngineKind, Workload
from services.serving.recommend import recommend, vram_budget

_GB = 1024**3


def _profile(
    *,
    system: str,
    arch: str,
    backend: ComputeBackend,
    vram: int | None = None,
    ram: int | None = None,
    accel_kind: AcceleratorKind | None = None,
) -> HardwareProfile:
    accels = []
    if accel_kind is not None:
        accels = [
            Accelerator(
                name="GPU",
                kind=accel_kind,
                vram_bytes=vram,
                unified=accel_kind == AcceleratorKind.metal,
            )
        ]
    return HardwareProfile(
        memory=MemoryInfo(total_bytes=ram, available_bytes=ram),
        accelerators=accels,
        compute_backend=backend,
        platform=PlatformInfo(system=system, release="x", arch=arch),
    )


def _apple() -> HardwareProfile:
    return _profile(
        system="Darwin", arch="arm64", backend=ComputeBackend.metal,
        vram=96 * _GB, ram=128 * _GB, accel_kind=AcceleratorKind.metal,
    )


def test_apple_silicon_recommends_mlx_first_llamacpp_baseline():
    recs = recommend(_apple())
    assert [r.rank for r in recs] == sorted(r.rank for r in recs)  # rank-ordered
    top = recs[0]
    assert top.engine == EngineKind.mlx and top.rank == 1 and top.available
    assert top.workloads == [Workload.chat]
    llama = next(r for r in recs if r.engine == EngineKind.llama_cpp)
    assert llama.available and llama.rank == 2
    assert Workload.embedding in llama.workloads


def test_cuda_host_leads_with_llamacpp_and_marks_mlx_unavailable():
    recs = recommend(
        _profile(
            system="Linux", arch="x86_64", backend=ComputeBackend.cuda,
            vram=24 * _GB, ram=64 * _GB, accel_kind=AcceleratorKind.cuda,
        )
    )
    assert recs[0].engine == EngineKind.llama_cpp and recs[0].rank == 1 and recs[0].available
    mlx = next(r for r in recs if r.engine == EngineKind.mlx)
    assert not mlx.available


def test_vram_budget_prefers_accelerator_then_falls_back_to_ram():
    gpu = _profile(
        system="Linux", arch="x86_64", backend=ComputeBackend.cuda,
        vram=24 * _GB, ram=64 * _GB, accel_kind=AcceleratorKind.cuda,
    )
    assert vram_budget(gpu) == 24 * _GB
    cpu = _profile(system="Linux", arch="x86_64", backend=ComputeBackend.cpu, ram=16 * _GB)
    assert vram_budget(cpu) == 16 * _GB
