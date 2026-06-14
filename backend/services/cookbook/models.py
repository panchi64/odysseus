"""Cookbook value types — the hardware profile and the model catalog shapes.

Plain Pydantic models (nothing persisted here yet, so no SQLModel / Alembic). The
load-bearing rule is **degrade, don't crash**: every probed hardware field is
optional, so an absent probe leaves a ``null`` rather than sinking the profile. The
catalog/recommendation types mirror what the frontend's LOCAL MODELS tab renders.
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


class Suitability(StrEnum):
    """How well a model fits the host, in the frontend's three-state vocabulary."""

    nominal = "nominal"
    warn = "warn"
    alert = "alert"


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
    accelerator family; ``simulated`` marks an operator-supplied what-if profile
    (the hardware-simulation seam) rather than a live probe."""

    cpu: CpuInfo = Field(default_factory=CpuInfo)
    memory: MemoryInfo = Field(default_factory=MemoryInfo)
    accelerators: list[Accelerator] = Field(default_factory=list)
    compute_backend: ComputeBackend = ComputeBackend.cpu
    platform: PlatformInfo
    runtimes: list[ServingRuntime] = Field(default_factory=list)
    simulated: bool = False
    source: str = "probe"  # "probe" | "simulated"


# --- model catalog ----------------------------------------------------------


class Capabilities(BaseModel):
    """What a model can do — enriched from OpenRouter where available, else
    derived from HuggingFace metadata heuristics."""

    tools: bool = False
    vision: bool = False
    thinking: bool = False
    embedding: bool = False
    image_gen: bool = False


class QuantVariant(BaseModel):
    label: str  # "Q4_K_M", "Q8_0", "MLX-4bit", …
    bits_per_weight: float
    size_bytes: int  # exact on-disk download size


class CatalogModel(BaseModel):
    """One distinct model (quant forks collapsed into ``quants``)."""

    id: str  # the HF repo id of the canonical/base model
    name: str
    family: str | None = None  # "qwen", "llama", "deepseek", …
    params_b: float | None = None  # billions of parameters
    context_default: int | None = None
    capabilities: Capabilities = Field(default_factory=Capabilities)
    description: str | None = None
    license: str | None = None
    gated: bool = False  # requires accepting terms before download
    quants: list[QuantVariant] = Field(default_factory=list)
    # Adoption signals (HuggingFace) — the fallback when there's no Arena Elo.
    created_at: str | None = None  # ISO-8601 repo creation timestamp
    downloads: int = 0
    likes: int = 0
    # LMArena Chatbot Arena Elo (human-preference quality), when the model is ranked.
    arena_elo: int | None = None
    # 0..1 quality, stamped at build time: Arena Elo where available, else adoption.
    quality_score: float = 0.0


class CompatibleModel(BaseModel):
    """A single (model, quant) option scored against a hardware profile. The list is
    ranked, not curated — there is deliberately no 'recommended' pick to maintain."""

    model_id: str
    name: str
    params_b: float | None
    quant: str
    size_bytes: int
    est_runtime_bytes: int
    suitability: Suitability
    fits: bool
    capabilities: Capabilities = Field(default_factory=Capabilities)
    arena_elo: int | None = None
    quality_score: float = 0.0
    detail: str = ""
