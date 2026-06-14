"""Model-quality sources — the pluggable signal behind the ranking.

The Cookbook ranks models by hardware fit, then *quality*. Quality comes from a live,
external benchmark source behind a small seam, so we can trial several and keep the
best: each ``QualitySource`` returns a ``{normalize_name: ModelQuality}`` map keyed the
same way catalog ids normalize, and the catalog stamps every model from it. A model the
active source doesn't cover falls through to family-reputation, then an adoption proxy
(``compute_quality`` below).

Three adapters, in descending day-one coverage / ascending zero-setup:
  - ``ArtificialAnalysisSource`` — documented free API (``x-api-key``); one comparable
    Intelligence Index (+ per-task indices); adds new flagships within days.
  - ``LlmStatsSource`` — broadest/freshest on paper but an undocumented, auth-gated API,
    parsed defensively. Experimental.
  - ``LMArenaSource`` — keyless human-preference Elo via the HF datasets-server mirror of
    the official leaderboard; the zero-setup default, but it lags new releases.

Everything is best-effort over plain ``httpx``: an unavailable or keyless source returns
an empty map (never raises) and the scorer degrades to the next tier.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import Protocol

import httpx
from pydantic import BaseModel

from .sources import normalize_name

logger = logging.getLogger(__name__)


# --- the quality value type + the seam --------------------------------------


class ModelQuality(BaseModel):
    """One model's quality from the active source. ``score`` (normalized 0..1) is what
    the ranker consumes; ``display``/``metric`` are the source's native headline figure
    for the UI (an Elo, an index); per-task fields are optional future columns."""

    score: float
    display: float
    metric: str  # short UI label: "ELO", "INTELLIGENCE", "SCORE"
    coding: float | None = None
    reasoning: float | None = None


class QualitySource(Protocol):
    name: str

    async def scores(self) -> dict[str, ModelQuality]:
        """``normalize_name`` → quality for every model the source ranks."""
        ...


# --- the tiered 0..1 scorer (source → family → adoption) --------------------
#
# Quality, in priority of signal strength:
#  1. the model's own benchmark score (normalized 0..1) — the gold signal;
#  2. its FAMILY's standing — a brand-new release (Gemma 4, Qwen 3.6) the source hasn't
#     rated yet inherits its family's proven tier, discounted + freshness-lifted, so it
#     ranks with its lineage rather than sinking below an older rated sibling;
#  3. an adoption proxy (downloads/likes/recency), capped low, for unknown lineages.
# Family reputation is derived live from which models ARE benchmarked — no maintained list.
_BENCH_FLOOR = 0.40  # benchmarked models occupy [0.40, 1.0]
_FAMILY_TRUST = 0.85  # how much of its family's frontier an unrated model inherits
_FAMILY_BASE = 0.35  # floor of the family-reputation band
_FAMILY_SCORE_W = 0.50  # weight on the family frontier within that band
_FAMILY_RECENCY_W = 0.12  # freshness lift within the family band
_ADOPT_CEIL = 0.35  # unknown lineage tops out here (kept below any real benchmark)

# Adoption-proxy weights. Likes lead — a community endorsement a flagship earns
# (thousands) but a viral junk merge never gets (tens).
_W_LIKES = 0.55
_W_DOWNLOADS = 0.30
_W_RECENCY = 0.15
_RECENCY_HALF_LIFE_DAYS = 270.0

# LMArena Elo → 0..1 band (LMArena-specific; other sources normalize to their own scale).
_ELO_MIN = 1100.0
_ELO_MAX = 1400.0


def _recency(created_at: str | None, now: datetime) -> float:
    if not created_at:
        return 0.5
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return 0.5
    age_days = max((now - created).total_seconds() / 86_400.0, 0.0)
    return 0.5 ** (age_days / _RECENCY_HALF_LIFE_DAYS)


def _elo_norm(elo: float) -> float:
    return min(max((elo - _ELO_MIN) / (_ELO_MAX - _ELO_MIN), 0.0), 1.0)


def _adoption_score(created_at: str | None, downloads: int, likes: int, now: datetime) -> float:
    likes_norm = min(math.log10(likes + 1) / 4.0, 1.0)
    downloads_norm = min(math.log10(downloads + 1) / 7.0, 1.0)
    return (
        _W_LIKES * likes_norm
        + _W_DOWNLOADS * downloads_norm
        + _W_RECENCY * _recency(created_at, now)
    )


def compute_quality(
    bench_score: float | None,
    family_score: float | None,
    created_at: str | None,
    downloads: int,
    likes: int,
    *,
    now: datetime,
) -> float:
    """0..1 quality from the three tiers above. ``bench_score``/``family_score`` are
    already-normalized 0..1 figures from the active source (the family one being its
    lineage's frontier); ``None`` falls through to the next tier."""
    if bench_score is not None:
        return _BENCH_FLOOR + (1.0 - _BENCH_FLOOR) * bench_score
    if family_score is not None:
        band = _FAMILY_BASE + _FAMILY_SCORE_W * family_score * _FAMILY_TRUST
        return min(band + _FAMILY_RECENCY_W * _recency(created_at, now), 0.97)
    return _ADOPT_CEIL * _adoption_score(created_at, downloads, likes, now)


# --- shared parse helpers ----------------------------------------------------


def _as_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return None


def _first_present(row: dict, keys: tuple[str, ...]) -> object | None:
    for key in keys:
        if row.get(key) is not None:
            return row[key]
    return None


# --- LMArena (keyless, the zero-setup default) ------------------------------

# LMArena Chatbot Arena Elo via the HF datasets-server REST API (no auth). The
# `mathewhe/chatbot-arena-elo` dataset is an auto-updated mirror of the official
# leaderboard. Models are joined by fuzzy normalized name.
_DATASETS_ROWS = "https://datasets-server.huggingface.co/rows"
_ARENA_DATASET = "mathewhe/chatbot-arena-elo"
_ARENA_MAX_ROWS = 400


class LMArenaSource:
    name = "lmarena"

    def __init__(self, client: httpx.AsyncClient, *, timeout_s: float = 20.0) -> None:
        self._client = client
        self._timeout = timeout_s

    async def scores(self) -> dict[str, ModelQuality]:
        out: dict[str, ModelQuality] = {}
        try:
            for offset in range(0, _ARENA_MAX_ROWS, 100):
                resp = await self._client.get(
                    _DATASETS_ROWS,
                    params={
                        "dataset": _ARENA_DATASET,
                        "config": "default",
                        "split": "train",
                        "offset": offset,
                        "length": 100,
                    },
                    timeout=self._timeout,
                )
                resp.raise_for_status()
                rows = resp.json().get("rows", [])
                if not rows:
                    break
                for entry in rows:
                    row = entry.get("row", {})
                    name, score = row.get("Model"), row.get("Arena Score")
                    elo = _as_float(score)
                    if name and elo is not None:
                        out[normalize_name(name)] = ModelQuality(
                            score=_elo_norm(elo), display=round(elo), metric="ELO"
                        )
        except (httpx.HTTPError, ValueError, KeyError):
            logger.warning("cookbook: LMArena leaderboard fetch failed", exc_info=True)
            return out  # whatever pages we got (possibly empty); never fatal
        return out


# --- Artificial Analysis (documented free API, x-api-key) -------------------

_AA_MODELS = "https://artificialanalysis.ai/api/v2/data/llms/models"


class ArtificialAnalysisSource:
    name = "artificial_analysis"

    def __init__(self, client: httpx.AsyncClient, *, api_key: str, timeout_s: float = 20.0) -> None:
        self._client = client
        self._api_key = api_key
        self._timeout = timeout_s

    async def scores(self) -> dict[str, ModelQuality]:
        if not self._api_key:
            return {}
        try:
            resp = await self._client.get(
                _AA_MODELS, headers={"x-api-key": self._api_key}, timeout=self._timeout
            )
            resp.raise_for_status()
            payload = resp.json()
        except (httpx.HTTPError, ValueError):
            logger.warning("cookbook: Artificial Analysis fetch failed", exc_info=True)
            return {}
        rows = payload.get("data") if isinstance(payload, dict) else payload
        out: dict[str, ModelQuality] = {}
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            name = row.get("name") or row.get("slug")
            evals = row.get("evaluations") if isinstance(row.get("evaluations"), dict) else {}
            index = _as_float(
                evals.get("artificial_analysis_intelligence_index")
                or row.get("artificial_analysis_intelligence_index")
            )
            if not name or index is None:
                continue
            quality = ModelQuality(
                score=min(max(index / 100.0, 0.0), 1.0),
                display=round(index, 1),
                metric="INTELLIGENCE",
                coding=_as_float(evals.get("artificial_analysis_coding_index")),
                reasoning=_as_float(evals.get("artificial_analysis_math_index")),
            )
            # Index under both the display name and the stable slug to widen the join.
            out[normalize_name(name)] = quality
            if slug := row.get("slug"):
                out.setdefault(normalize_name(slug), quality)
        return out


# --- llm-stats.com (undocumented API — defensive parse) ---------------------

_LLM_STATS_MODELS = "https://api.llm-stats.com/stats/v1/models"


class LlmStatsSource:
    name = "llm_stats"

    def __init__(self, client: httpx.AsyncClient, *, api_key: str, timeout_s: float = 20.0) -> None:
        self._client = client
        self._api_key = api_key
        self._timeout = timeout_s

    async def scores(self) -> dict[str, ModelQuality]:
        if not self._api_key:
            return {}
        try:
            resp = await self._client.get(
                _LLM_STATS_MODELS,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=self._timeout,
            )
            resp.raise_for_status()
            payload = resp.json()
        except (httpx.HTTPError, ValueError):
            logger.warning("cookbook: llm-stats fetch failed", exc_info=True)
            return {}
        # Schema is undocumented — read the model list from the likely containers and the
        # score from a small candidate set, skipping rows that don't fit.
        if isinstance(payload, dict):
            rows = payload.get("data") or payload.get("models") or payload.get("results") or []
        else:
            rows = payload
        out: dict[str, ModelQuality] = {}
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            name = _first_present(row, ("name", "model", "slug", "id"))
            raw = _first_present(
                row,
                ("llm_stats_score", "score", "composite_score", "composite", "intelligence"),
            )
            value = _as_float(raw)
            if name is None or value is None:
                continue
            # Accept either a 0..1 or a 0..100 native scale.
            norm = value / 100.0 if value > 1.0 else value
            out[normalize_name(str(name))] = ModelQuality(
                score=min(max(norm, 0.0), 1.0), display=round(value, 1), metric="SCORE"
            )
        return out


# --- selection ---------------------------------------------------------------


def build_quality_source(
    client: httpx.AsyncClient,
    name: str,
    *,
    aa_api_key: str | None = None,
    llm_stats_api_key: str | None = None,
    timeout_s: float = 20.0,
) -> QualitySource:
    """The configured source, falling back to keyless LMArena when the chosen source has
    no key (so the Cookbook still ranks with zero setup)."""
    if name == "artificial_analysis" and aa_api_key:
        return ArtificialAnalysisSource(client, api_key=aa_api_key, timeout_s=timeout_s)
    if name == "llm_stats" and llm_stats_api_key:
        return LlmStatsSource(client, api_key=llm_stats_api_key, timeout_s=timeout_s)
    if name not in ("lmarena", "artificial_analysis", "llm_stats"):
        logger.warning("cookbook: unknown quality source %r; using LMArena", name)
    return LMArenaSource(client, timeout_s=timeout_s)
