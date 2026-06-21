"""Cookbook value types — the host hardware profile.

Plain Pydantic models (nothing persisted here yet, so no SQLModel / Alembic). The
load-bearing rule is **degrade, don't crash**: every probed hardware field is
optional, so an absent probe leaves a ``null`` rather than sinking the profile.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class AcceleratorKind(StrEnum):
    metal = "metal"
    cuda = "cuda"
    rocm = "rocm"
    cpu = "cpu"


class ComputeBackend(StrEnum):
    metal = "metal"
    cuda = "cuda"
    rocm = "rocm"
    cpu = "cpu"


# --- hardware profile -------------------------------------------------------


class CpuInfo(BaseModel):
    model: str | None = None
    physical_cores: int | None = None
    logical_cores: int | None = None


class MemoryInfo(BaseModel):
    total_bytes: int | None = None
    available_bytes: int | None = None


class Accelerator(BaseModel):
    name: str
    kind: AcceleratorKind
    vram_bytes: int | None = None
    # Apple Silicon shares one memory pool between CPU and GPU — the VRAM figure is
    # a budget carved out of system RAM, not a separate bank.
    unified: bool = False
    gpu_cores: int | None = None


class PlatformInfo(BaseModel):
    system: str  # platform.system() — "Darwin" / "Linux"
    release: str
    arch: str  # platform.machine() — "arm64" / "x86_64"


class ServingRuntime(BaseModel):
    name: str  # "ollama" / "llama.cpp" / "mlx-lm" / "vllm"
    version: str | None = None  # None when present but unparsable
    available: bool


class HardwareProfile(BaseModel):
    """A snapshot of what the host can run. ``compute_backend`` is the primary
    accelerator family."""

    cpu: CpuInfo = Field(default_factory=CpuInfo)
    memory: MemoryInfo = Field(default_factory=MemoryInfo)
    accelerators: list[Accelerator] = Field(default_factory=list)
    compute_backend: ComputeBackend = ComputeBackend.cpu
    platform: PlatformInfo
    runtimes: list[ServingRuntime] = Field(default_factory=list)
