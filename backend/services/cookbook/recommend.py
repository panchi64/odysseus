"""Hardware-adaptive scoring — rank catalog models against a hardware profile.

Pure functions over a profile + catalog, so the same code scores the *detected*
host and an operator-supplied *simulated* one (the what-if path). For each model we
pick the best quant the host can hold, estimate its runtime footprint against the
host's memory budget, and label it nominal/warn/alert. The estimate is deliberately
simple and tunable — exact weights from HF's on-disk size, plus a context-scaled KV
term and a flat overhead.
"""

from __future__ import annotations

from .models import (
    CatalogModel,
    CompatibleModel,
    ComputeBackend,
    HardwareProfile,
    QuantVariant,
    Suitability,
)

# KV-cache bytes per context token per billion parameters — a coarse stand-in for the
# real per-architecture figure (layers × hidden-dim), good enough at ranking scale.
_KV_BYTES_PER_TOKEN_PER_B = 1024.0
# Runtime/activation overhead above the weights themselves.
_OVERHEAD_FRACTION = 0.10
# Assumed params when the catalog didn't surface a count (KV scaling only).
_DEFAULT_PARAMS_B = 7.0
# Default context when a model didn't declare one.
_DEFAULT_CONTEXT = 4096
# A model is "nominal" only if it fits inside this fraction of the budget — leaving
# headroom for the OS, other apps, and estimate error.
_NOMINAL_HEADROOM = 0.80
# Below this effective bits-per-weight a quant is a quality compromise (Q1/Q2-class):
# it may fit, but it shouldn't be presented as a comfortable "nominal" choice — that
# would rank a barely-usable quant of a huge model above a clean fit of a smaller one.
_MIN_QUALITY_BPW = 3.5


def estimate_runtime_bytes(weight_bytes: int, params_b: float | None, context: int | None) -> int:
    """Estimated peak memory to serve a quant: on-disk weights + KV cache + overhead."""
    kv = (context or _DEFAULT_CONTEXT) * (params_b or _DEFAULT_PARAMS_B) * _KV_BYTES_PER_TOKEN_PER_B
    overhead = weight_bytes * _OVERHEAD_FRACTION
    return int(weight_bytes + kv + overhead)


def memory_budget(profile: HardwareProfile) -> int | None:
    """The memory a model may occupy on this host: discrete VRAM for GPUs, the unified
    budget for Apple Silicon, system RAM for a CPU-only host. ``None`` ⇒ unknown."""
    backend = profile.compute_backend
    if backend in (ComputeBackend.cuda, ComputeBackend.rocm):
        vram = sum(a.vram_bytes for a in profile.accelerators if a.vram_bytes)
        return vram or None
    if backend == ComputeBackend.metal:
        for accel in profile.accelerators:
            if accel.unified and accel.vram_bytes:
                return accel.vram_bytes
        total = profile.memory.total_bytes
        return int(total * 0.75) if total else None
    return profile.memory.total_bytes


def _score(budget: int | None, est_bytes: int) -> tuple[Suitability, bool]:
    if budget is None:
        return Suitability.warn, False  # can't size the host — caution, don't claim a fit
    if est_bytes <= _NOMINAL_HEADROOM * budget:
        return Suitability.nominal, True
    if est_bytes <= budget:
        return Suitability.warn, True
    return Suitability.alert, False


def _is_mlx(model: CatalogModel) -> bool:
    return model.id.startswith("mlx-community/") or any(
        q.label.upper().startswith("MLX") for q in model.quants
    )


def _platform_compatible(profile: HardwareProfile, model: CatalogModel) -> bool:
    """MLX models only make sense on Apple Silicon; GGUF runs on any backend."""
    if _is_mlx(model):
        return profile.compute_backend == ComputeBackend.metal
    return True


def _best_quant(
    model: CatalogModel, budget: int | None
) -> tuple[QuantVariant, int, Suitability, bool]:
    """Pick the highest-quality quant the host can hold: the most bits that stays
    nominal, else the most bits that merely fits, else the smallest (flagged alert)."""
    scored = [
        (q, est, *_score(budget, est))
        for q in model.quants
        for est in [estimate_runtime_bytes(q.size_bytes, model.params_b, model.context_default)]
    ]
    nominal = [s for s in scored if s[2] == Suitability.nominal]
    if nominal:
        return max(nominal, key=lambda s: s[0].bits_per_weight)
    fitting = [s for s in scored if s[3]]
    if fitting:
        return max(fitting, key=lambda s: s[0].bits_per_weight)
    return min(scored, key=lambda s: s[1])  # nothing fits — the smallest, as an alert


def _detail(suitability: Suitability, est_bytes: int, budget: int | None) -> str:
    gib = est_bytes / (1024**3)
    if budget is None:
        return f"~{gib:.1f} GB — host memory unknown"
    budget_gib = budget / (1024**3)
    if suitability == Suitability.nominal:
        return f"~{gib:.1f} GB — fits comfortably in {budget_gib:.0f} GB"
    if suitability == Suitability.warn:
        return f"~{gib:.1f} GB — tight against {budget_gib:.0f} GB"
    return f"~{gib:.1f} GB — exceeds {budget_gib:.0f} GB"


_SUITABILITY_RANK = {Suitability.nominal: 0, Suitability.warn: 1, Suitability.alert: 2}


def compatible_models(
    profile: HardwareProfile, catalog: list[CatalogModel]
) -> list[CompatibleModel]:
    """Rank the models the host can run — by hardware fit, then live quality. Not a
    curated recommendation: the ordering is computed, with no model singled out."""
    budget = memory_budget(profile)
    recs: list[CompatibleModel] = []
    for model in catalog:
        if not _platform_compatible(profile, model) or not model.quants:
            continue
        quant, est, suitability, fits = _best_quant(model, budget)
        # A model that only fits at a very low-bit quant is a compromise, not a
        # comfortable fit — cap it at warn so it can't outrank a clean smaller model.
        low_quant = quant.bits_per_weight < _MIN_QUALITY_BPW
        if suitability == Suitability.nominal and low_quant:
            suitability = Suitability.warn
        detail = (
            f"~{est / 1024**3:.1f} GB — only a low-quality {quant.label} quant fits"
            if low_quant and fits
            else _detail(suitability, est, budget)
        )
        recs.append(
            CompatibleModel(
                model_id=model.id,
                name=model.name,
                params_b=model.params_b,
                quant=quant.label,
                size_bytes=quant.size_bytes,
                est_runtime_bytes=est,
                suitability=suitability,
                fits=fits,
                capabilities=model.capabilities,
                quality_display=model.quality_display,
                quality_metric=model.quality_metric,
                quality_score=model.quality_score,
                detail=detail,
            )
        )
    # Best fit first; within a band, the higher-quality (newer, more-adopted) model —
    # so an old model that merely fits can't outrank a current one. Params/size break ties.
    recs.sort(
        key=lambda r: (
            _SUITABILITY_RANK[r.suitability],
            -r.quality_score,
            -(r.params_b or 0),
            r.size_bytes,
        )
    )
    return recs
