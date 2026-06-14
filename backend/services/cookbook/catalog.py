"""The cached model catalog — one read-through facade over the live sources.

Building the catalog is several network calls (an HF list, a file tree per model, an
OpenRouter list), so it is **never** on the hot path: a TTL cache holds the resolved
list and a background refresh replaces it. The degrade rule mirrors search/sandbox —
if the authoritative HF spine is unreachable and we have no cache, raise
``DegradedCapabilityError`` (the route turns that into an explicit "catalog
unavailable", never a fabricated list). OpenRouter enrichment failing is softer: the
catalog still builds on HF metadata heuristics.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime

import httpx

from core.exceptions import DegradedCapabilityError

from .models import CatalogModel
from .sources import (
    HuggingFaceCatalog,
    LeaderboardEnricher,
    OpenRouterEnricher,
    compute_quality,
    normalize_name,
)

logger = logging.getLogger(__name__)


class ModelCatalog:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        hf_token: str | None = None,
        ttl_s: float = 86_400.0,
        list_limit: int = 60,
        max_models: int = 24,
    ) -> None:
        self._client = client
        self._hf_token = hf_token
        self._ttl_s = ttl_s
        self._list_limit = list_limit
        self._max_models = max_models
        self._cache: list[CatalogModel] | None = None
        self._fetched_at: float | None = None
        self._lock = asyncio.Lock()
        # Quality signals from the last build, reused to score search results.
        self._elos: dict[str, int] = {}
        self._family_rep: dict[str, int] = {}

    def _fresh(self) -> bool:
        return (
            self._cache is not None
            and self._fetched_at is not None
            and (time.monotonic() - self._fetched_at) < self._ttl_s
        )

    async def get(self) -> list[CatalogModel]:
        """The cached catalog, refreshing past the TTL. Serves a stale copy if a
        refresh fails; raises ``DegradedCapabilityError`` only when there is nothing
        to serve at all."""
        if self._fresh():
            return self._cache  # type: ignore[return-value]
        async with self._lock:
            if self._fresh():
                return self._cache  # type: ignore[return-value]
            try:
                catalog = await self._build()
            except (httpx.HTTPError, ValueError) as exc:
                if self._cache is not None:
                    logger.warning("cookbook: catalog refresh failed; serving stale", exc_info=True)
                    return self._cache
                raise DegradedCapabilityError("model catalog unavailable") from exc
            self._cache = catalog
            self._fetched_at = time.monotonic()
            return catalog

    async def refresh(self) -> list[CatalogModel]:
        self._fetched_at = None
        return await self.get()

    async def search(self, query: str) -> list[CatalogModel]:
        """Models matching a free-text query, scored with the same quality signals as
        the curated catalog. Best-effort warms those signals first (cached)."""
        try:
            await self.get()  # populate self._elos / self._family_rep (cached)
        except DegradedCapabilityError:
            pass  # search can still rank by adoption if the leaderboard is unavailable
        hf = HuggingFaceCatalog(self._client, token=self._hf_token)
        models = await hf.search(query, max_models=self._max_models)
        self._score(models)
        return models

    async def _build(self) -> list[CatalogModel]:
        hf = HuggingFaceCatalog(self._client, token=self._hf_token)
        models = await hf.fetch(limit=self._list_limit, max_models=self._max_models)
        try:
            await OpenRouterEnricher(self._client).apply(models)
        except (httpx.HTTPError, ValueError):
            # Capability enrichment is optional — HF heuristics already populated flags.
            logger.warning("cookbook: OpenRouter enrichment failed; using HF heuristics",
                           exc_info=True)
        # A failed leaderboard fetch just leaves every model on the adoption fallback.
        try:
            self._elos = await LeaderboardEnricher(self._client).elos()
        except (httpx.HTTPError, ValueError, KeyError):
            logger.warning("cookbook: leaderboard fetch failed; quality falls back to adoption",
                           exc_info=True)
            self._elos = {}
        # Family reputation, derived live: the best Arena Elo seen for each family.
        self._family_rep = {}
        for model in models:
            elo = self._elos.get(normalize_name(model.id))
            if elo is not None and model.family:
                self._family_rep[model.family] = max(self._family_rep.get(model.family, 0), elo)
        self._score(models)
        return models

    def _score(self, models: list[CatalogModel]) -> None:
        """Stamp Arena Elo + quality on each model from the cached signals. Quality is
        own Elo, else the family's Arena standing, else an adoption proxy."""
        now = datetime.now(UTC)
        for model in models:
            model.arena_elo = self._elos.get(normalize_name(model.id))
            model.quality_score = compute_quality(
                model.arena_elo,
                self._family_rep.get(model.family) if model.family else None,
                model.created_at,
                model.downloads,
                model.likes,
                now=now,
            )
