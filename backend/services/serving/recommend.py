"""Engine recommendation — a pure mapping from a hardware profile to ranked engines.

No I/O, fully testable with crafted profiles. The strategy mirrors the engine
decision: **llama.cpp is the universal baseline** (chat + embeddings, every
platform), and **MLX is an Apple-Silicon chat speed upgrade** layered on top.

``available`` is computed from the profile here (MLX needs arm64 macOS; llama.cpp
runs everywhere). The service overlays each adapter's real ``is_installed()`` onto
the result so the UI can distinguish a ready runtime from one that will be fetched
on first serve.
"""

from __future__ import annotations

from services.cookbook.models import ComputeBackend, HardwareProfile

from .models import EngineKind, EngineRecommendation, Workload

# Leave headroom below the raw budget — weights aren't the only thing resident
# (KV cache, runtime, the OS). The pre-flight guard fits a model under this slice.
_FIT_FRACTION = 0.9


def vram_budget(profile: HardwareProfile) -> int | None:
    """The memory a model can realistically claim: the largest accelerator's VRAM
    (Apple Silicon's is a unified-RAM slice), else total system RAM, else unknown."""
    vrams = [a.vram_bytes for a in profile.accelerators if a.vram_bytes]
    if vrams:
        return max(vrams)
    return profile.memory.total_bytes


def usable_budget(budget: int | None) -> int | None:
    """The slice of the budget a model can actually claim once fit-fraction headroom is
    held back (KV cache, runtime, the OS). ``None`` when the budget is unknown. This is
    the ceiling the pre-flight headroom guard sums running models against."""
    return int(budget * _FIT_FRACTION) if budget is not None else None


def _is_apple_silicon(profile: HardwareProfile) -> bool:
    return profile.platform.system == "Darwin" and profile.platform.arch == "arm64"


_BACKEND_REASON: dict[ComputeBackend, str] = {
    ComputeBackend.cuda: "Cross-platform baseline; runs on your NVIDIA GPU (CUDA).",
    ComputeBackend.rocm: "Cross-platform baseline; runs on your AMD GPU (ROCm).",
    ComputeBackend.metal: (
        "Cross-platform baseline; serves embeddings and is the dependable fallback "
        "(Metal-accelerated here)."
    ),
    ComputeBackend.cpu: "Cross-platform baseline; runs on CPU when no accelerator is present.",
}


def recommend(profile: HardwareProfile) -> list[EngineRecommendation]:
    """Rank the engines for this host. llama.cpp is always available; MLX leads for
    chat on Apple Silicon and is listed as known-but-unavailable elsewhere."""
    apple = _is_apple_silicon(profile)

    recs: list[EngineRecommendation] = []

    if apple:
        # MLX leads for chat; llama.cpp is the embeddings + fallback baseline.
        recs.append(
            EngineRecommendation(
                engine=EngineKind.mlx, rank=1, available=True,
                reason="Fastest on Apple Silicon for chat (Metal-native MLX).",
                workloads=[Workload.chat],
            )
        )
        llama_rank = 2
    else:
        llama_rank = 1

    llama_reason = _BACKEND_REASON.get(
        profile.compute_backend, _BACKEND_REASON[ComputeBackend.cpu]
    )
    recs.append(
        EngineRecommendation(
            engine=EngineKind.llama_cpp, rank=llama_rank, available=True,
            reason=llama_reason,
            workloads=[Workload.chat, Workload.embedding],
        )
    )

    if not apple:
        # Still surface MLX so the UI is honest about what the host can't run.
        recs.append(
            EngineRecommendation(
                engine=EngineKind.mlx, rank=llama_rank + 1, available=False,
                reason="Apple Silicon only — not available on this host.",
                workloads=[Workload.chat],
            )
        )

    return sorted(recs, key=lambda r: r.rank)
