"""Compare the Cookbook's quality sources against the *live* catalog — the tool for
deciding which source to ship.

Builds the HuggingFace catalog once (real network), then scores it under each available
source (LMArena always; Artificial Analysis / llm-stats when their keys are set) and
prints, side by side, the join **coverage** and the resulting top-N compatible-model
ranking. Read it to pick the source that (a) matches the most catalog models and (b) puts
the latest flagships on top, then set ``ODYSSEUS_COOKBOOK_QUALITY_SOURCE`` to the winner.

    cd backend
    ODYSSEUS_ARTIFICIAL_ANALYSIS_API_KEY=… ODYSSEUS_LLM_STATS_API_KEY=… \
        uv run python scripts/compare_quality_sources.py [--top 25] [--limit 80]

Read-only, single-operator: it only GETs public/keyed APIs and prints. No app state.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.cookbook import hardware  # noqa: E402
from services.cookbook.models import CatalogModel, HardwareProfile  # noqa: E402
from services.cookbook.quality import (  # noqa: E402
    ArtificialAnalysisSource,
    LlmStatsSource,
    LMArenaSource,
    ModelQuality,
    QualitySource,
    compute_quality,
)
from services.cookbook.recommend import compatible_models  # noqa: E402
from services.cookbook.sources import (  # noqa: E402
    HuggingFaceCatalog,
    OpenRouterEnricher,
    normalize_name,
)


def _score_under(models: list[CatalogModel], scores: dict[str, ModelQuality]) -> int:
    """Stamp quality on every model from one source's scores (same tiering as the live
    catalog). Returns how many models matched the source directly (the coverage count)."""
    now = datetime.now(UTC)
    family_rep: dict[str, float] = {}
    for model in models:
        q = scores.get(normalize_name(model.id))
        if q is not None and model.family:
            family_rep[model.family] = max(family_rep.get(model.family, 0.0), q.score)
    matched = 0
    for model in models:
        q = scores.get(normalize_name(model.id))
        if q is not None:
            matched += 1
        model.quality_display = q.display if q else None
        model.quality_metric = q.metric if q else None
        model.quality_score = compute_quality(
            q.score if q else None,
            family_rep.get(model.family) if model.family else None,
            model.created_at,
            model.downloads,
            model.likes,
            now=now,
        )
    return matched


def _print_ranking(name: str, profile: HardwareProfile, models: list[CatalogModel],
                   matched: int, top: int) -> list:
    ranked = compatible_models(profile, models)
    print(f"\n{'=' * 78}\n  SOURCE: {name}   "
          f"coverage: {matched}/{len(models)} models matched directly\n{'=' * 78}")
    print(f"  {'#':>2}  {'MODEL':<40} {'PARAMS':>7} {'QUANT':<8} {'METRIC':>10} {'Q':>5}  FIT")
    for i, r in enumerate(ranked[:top], 1):
        params = f"{r.params_b}B" if r.params_b else "—"
        metric = f"{r.quality_metric or '—'}:{r.quality_display:g}" if r.quality_display else "—"
        print(f"  {i:>2}  {r.name[:40]:<40} {params:>7} {r.quant:<8} "
              f"{metric:>10} {r.quality_score:>5.2f}  {r.suitability.value}")
    return ranked


def _divergence(rankings: dict[str, list]) -> None:
    """Models in some source's top-10 but absent from another's — where sources disagree."""
    tops = {name: [r.model_id for r in ranked[:10]] for name, ranked in rankings.items()}
    print(f"\n{'=' * 78}\n  TOP-10 DIVERGENCE\n{'=' * 78}")
    for name, ids in tops.items():
        others = {n: set(v) for n, v in tops.items() if n != name}
        unique = [mid for mid in ids if any(mid not in o for o in others.values())]
        if unique:
            print(f"  in {name}'s top-10 but not every other's:")
            for mid in unique:
                print(f"     - {mid}")


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--top", type=int, default=25, help="rows per source")
    ap.add_argument("--limit", type=int, default=80, help="HF trending repos to scan")
    ap.add_argument("--max-models", type=int, default=40, help="distinct models to size")
    args = ap.parse_args()

    aa_key = os.environ.get("ODYSSEUS_ARTIFICIAL_ANALYSIS_API_KEY")
    llm_stats_key = os.environ.get("ODYSSEUS_LLM_STATS_API_KEY")
    hf_token = os.environ.get("ODYSSEUS_HF_TOKEN")

    async with httpx.AsyncClient(follow_redirects=True) as client:
        print("probing hardware…")
        profile = await hardware.probe()
        print(f"  backend={profile.compute_backend.value} "
              f"ram={(profile.memory.total_bytes or 0) / 1024**3:.0f}GB")

        print(f"building HF catalog (limit={args.limit}, max_models={args.max_models})…")
        hf = HuggingFaceCatalog(client, token=hf_token)
        base = await hf.fetch(limit=args.limit, max_models=args.max_models)
        try:
            await OpenRouterEnricher(client).apply(base)
        except (httpx.HTTPError, ValueError):
            print("  (OpenRouter enrichment failed — capability flags from HF heuristics)")
        print(f"  {len(base)} distinct models")

        sources: list[QualitySource] = [LMArenaSource(client)]
        if aa_key:
            sources.append(ArtificialAnalysisSource(client, api_key=aa_key))
        else:
            print("  (no ODYSSEUS_ARTIFICIAL_ANALYSIS_API_KEY — skipping Artificial Analysis)")
        if llm_stats_key:
            sources.append(LlmStatsSource(client, api_key=llm_stats_key))
        else:
            print("  (no ODYSSEUS_LLM_STATS_API_KEY — skipping llm-stats)")

        rankings: dict[str, list] = {}
        for source in sources:
            scores = await source.scores()
            # Score a fresh copy per source so they don't clobber each other.
            models = [m.model_copy(deep=True) for m in base]
            matched = _score_under(models, scores)
            rankings[source.name] = _print_ranking(source.name, profile, models, matched, args.top)

        if len(rankings) > 1:
            _divergence(rankings)


if __name__ == "__main__":
    asyncio.run(main())
