"""CookbookService — the capability facade the router talks to.

Ties the three pieces together: the cached hardware profile (`hardware.probe`), the
cached live catalog (`ModelCatalog`), and the pure scorer (`recommend`). The hardware
profile is probed once and cached behind a lock (concurrent first-callers collapse to
one probe); `recommend` scores either the detected profile or an operator-supplied
simulated one through the same path.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from . import hardware
from .catalog import ModelCatalog
from .models import CompatibleModel, HardwareProfile
from .recommend import compatible_models as _compatible_models

logger = logging.getLogger(__name__)


class CookbookService:
    def __init__(
        self,
        http_client: httpx.AsyncClient,
        *,
        hf_token: str | None = None,
        catalog_ttl_s: float = 86_400.0,
        catalog_list_limit: int = 60,
        catalog_max_models: int = 24,
    ) -> None:
        self._catalog = ModelCatalog(
            http_client,
            hf_token=hf_token,
            ttl_s=catalog_ttl_s,
            list_limit=catalog_list_limit,
            max_models=catalog_max_models,
        )
        self._profile: HardwareProfile | None = None
        self._lock = asyncio.Lock()

    async def detect(self) -> HardwareProfile:
        """The host hardware profile, probed once and cached."""
        if self._profile is not None:
            return self._profile
        async with self._lock:
            if self._profile is None:
                self._profile = await hardware.probe()
            return self._profile

    async def refresh(self) -> HardwareProfile:
        """Re-probe the hardware (e.g. after the operator plugs in a GPU)."""
        async with self._lock:
            self._profile = await hardware.probe()
            return self._profile

    async def compatible_models(
        self, profile: HardwareProfile | None = None
    ) -> list[CompatibleModel]:
        """Rank the models that run on ``profile`` (detected if omitted, supplied for
        the hardware-simulation what-if). Ranked, not curated."""
        target = profile or await self.detect()
        catalog = await self._catalog.get()
        return _compatible_models(target, catalog)

    async def search(
        self, query: str, profile: HardwareProfile | None = None
    ) -> list[CompatibleModel]:
        """Find models matching ``query`` and score them against the host — for an
        operator checking a specific model they've heard about."""
        target = profile or await self.detect()
        matches = await self._catalog.search(query)
        return _compatible_models(target, matches)

    async def warmup(self) -> None:
        """Best-effort background priming at boot — probe the hardware and pull the
        catalog so the first request is cache-served. Failures are logged, not raised
        (a slow probe or an offline catalog must not break startup)."""
        try:
            await self.detect()
        except Exception:
            logger.warning("cookbook: hardware warm-up failed", exc_info=True)
        try:
            await self._catalog.get()
        except Exception:
            logger.warning("cookbook: catalog warm-up failed (offline?)", exc_info=True)
