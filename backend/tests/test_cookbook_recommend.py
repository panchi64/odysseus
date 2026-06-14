"""Recommendation scoring — pure functions over fixed profiles + a stub catalog.

No network: the catalog is hand-built. Asserts the suitability bands shift as the
memory budget shrinks, MLX models are filtered to Apple Silicon, and ranking puts the
higher-quality model first. The supplied-profile path is the simulation what-if.
"""

from __future__ import annotations

from services.cookbook.models import (
    Accelerator,
    AcceleratorKind,
    Capabilities,
    CatalogModel,
    ComputeBackend,
    HardwareProfile,
    MemoryInfo,
    PlatformInfo,
    QuantVariant,
    Suitability,
)
from services.cookbook.recommend import compatible_models

_GIB = 1024**3


def _mac(gb: int) -> HardwareProfile:
    """Apple Silicon: unified VRAM is a 75% slice of RAM."""
    return HardwareProfile(
        platform=PlatformInfo(system="Darwin", release="", arch="arm64"),
        memory=MemoryInfo(total_bytes=gb * _GIB, available_bytes=gb * _GIB),
        accelerators=[
            Accelerator(
                name="Apple", kind=AcceleratorKind.metal, vram_bytes=int(gb * _GIB * 0.75),
                unified=True,
            )
        ],
        compute_backend=ComputeBackend.metal,
    )


def _cuda(vram_gb: int) -> HardwareProfile:
    return HardwareProfile(
        platform=PlatformInfo(system="Linux", release="", arch="x86_64"),
        memory=MemoryInfo(total_bytes=64 * _GIB, available_bytes=32 * _GIB),
        accelerators=[Accelerator(name="NV", kind=AcceleratorKind.cuda, vram_bytes=vram_gb * _GIB)],
        compute_backend=ComputeBackend.cuda,
    )


def _gguf(repo: str, params: float, size_gb: float, *, tools: bool = True) -> CatalogModel:
    return CatalogModel(
        id=repo,
        name=repo.split("/")[-1],
        params_b=params,
        context_default=8192,
        capabilities=Capabilities(tools=tools),
        quants=[QuantVariant(label="Q4_K_M", bits_per_weight=4.5, size_bytes=int(size_gb * _GIB))],
    )


def _mlx(repo: str, size_gb: float) -> CatalogModel:
    return CatalogModel(
        id=repo,
        name=repo.split("/")[-1],
        params_b=7,
        context_default=4096,
        quants=[
            QuantVariant(label="MLX-4bit", bits_per_weight=4.5, size_bytes=int(size_gb * _GIB))
        ],
    )


def test_suitability_tracks_the_budget():
    model = _gguf("org/big", params=30, size_gb=20)  # ~20 GB weights, est ~22 GB

    def suitability(profile):
        return compatible_models(profile, [model])[0].suitability

    assert suitability(_mac(40)) == Suitability.nominal  # budget 30 GB
    assert suitability(_mac(32)) == Suitability.warn  # budget 24 GB
    assert suitability(_mac(24)) == Suitability.alert  # budget 18 GB


def test_mlx_filtered_to_apple_silicon():
    model = _mlx("mlx-community/foo-4bit", size_gb=4)
    assert compatible_models(_cuda(24), [model]) == []  # MLX makes no sense on CUDA
    assert len(compatible_models(_mac(40), [model])) == 1


def test_gguf_runs_on_any_backend():
    model = _gguf("org/small", params=7, size_gb=4)
    assert len(compatible_models(_cuda(24), [model])) == 1
    assert len(compatible_models(_mac(40), [model])) == 1


def test_ranks_by_quality_within_a_band():
    # Both fit nominally on a roomy host; the older/weaker model has more params but a
    # lower quality score — it must not outrank the newer, well-adopted one.
    old = _gguf("org/old-but-big", params=13, size_gb=8)
    old.quality_score = 0.2
    new = _gguf("org/new-and-good", params=7, size_gb=4)
    new.quality_score = 0.9
    recs = compatible_models(_mac(40), [old, new])
    assert [r.model_id for r in recs] == ["org/new-and-good", "org/old-but-big"]


def test_best_quant_picks_highest_bits_that_stays_nominal():
    model = CatalogModel(
        id="org/multi",
        name="multi",
        params_b=7,
        context_default=4096,
        quants=[
            QuantVariant(label="Q4_K_M", bits_per_weight=4.5, size_bytes=4 * _GIB),
            QuantVariant(label="Q8_0", bits_per_weight=8.5, size_bytes=8 * _GIB),
        ],
    )
    # Roomy host → the higher-quality Q8_0 is chosen.
    assert compatible_models(_mac(40), [model])[0].quant == "Q8_0"
