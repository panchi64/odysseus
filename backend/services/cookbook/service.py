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

from services.credential_store import CredentialStore
from services.settings_store import SettingsStore

from . import hardware
from .catalog import ModelCatalog
from .models import CompatibleModel, HardwareProfile
from .quality import (
    QUALITY_SOURCE_IDS,
    QUALITY_SOURCES,
    QualitySource,
    build_quality_source,
)
from .recommend import compatible_models as _compatible_models

logger = logging.getLogger(__name__)

# The persisted-settings key holding the operator's chosen ranking source.
_SOURCE_SETTING = "cookbook.quality_source"


class CookbookService:
    def __init__(
        self,
        http_client: httpx.AsyncClient,
        *,
        credentials: CredentialStore,
        settings: SettingsStore,
        owner_id: str,
        hf_token: str | None = None,
        catalog_ttl_s: float = 86_400.0,
        catalog_list_limit: int = 60,
        catalog_max_models: int = 24,
        quality_source: str = "lmarena",
        aa_api_key: str | None = None,
        llm_stats_api_key: str | None = None,
    ) -> None:
        self._http = http_client
        self._credentials = credentials
        self._settings = settings
        self._owner_id = owner_id
        # The env default; the operator's persisted choice (if any) overrides it.
        self._default_source = quality_source
        # Env-provided keys are the fallback when nothing is set in the credential store.
        self._aa_env = aa_api_key
        self._llm_env = llm_stats_api_key
        self._hf_env = hf_token
        self._catalog = ModelCatalog(
            http_client,
            resolve_runtime=self._resolve_runtime,
            ttl_s=catalog_ttl_s,
            list_limit=catalog_list_limit,
            max_models=catalog_max_models,
        )
        self._profile: HardwareProfile | None = None
        self._lock = asyncio.Lock()

    async def _resolve_runtime(self) -> tuple[QualitySource, str | None]:
        """The active quality source + HF token for a catalog build. Operator-set keys
        (the credential store) override the env defaults; ``build_quality_source`` falls
        back to keyless LMArena when the chosen source has no key either way. While the
        vault is locked the store yields ``None`` and we use the env fallback."""

        async def keyed(service: str, env: str | None) -> str | None:
            return await self._credentials.get_secret(self._owner_id, service) or env

        aa = await keyed("artificial_analysis", self._aa_env)
        llm = await keyed("llm_stats", self._llm_env)
        hf = await keyed("huggingface", self._hf_env)
        source = build_quality_source(
            self._http, await self.active_source(), aa_api_key=aa, llm_stats_api_key=llm
        )
        return source, hf

    async def active_source(self) -> str:
        """The operator's chosen ranking source, falling back to the env default. A
        stale/invalid stored value is ignored."""
        stored = await self._settings.get(self._owner_id, _SOURCE_SETTING)
        return stored if stored in QUALITY_SOURCE_IDS else self._default_source

    async def set_source(self, source: str) -> None:
        """Persist the ranking source and rebuild the catalog under it on next request."""
        if source not in QUALITY_SOURCE_IDS:
            raise ValueError(f"unknown quality source {source!r}")
        await self._settings.set(self._owner_id, _SOURCE_SETTING, source)
        self._catalog.invalidate()

    async def source_options(self) -> list[dict]:
        """Each selectable source + whether a key is available for it (a stored credential
        or the env fallback) — so the UI can flag a keyed source the operator can't use yet."""
        status = await self._credentials.status(self._owner_id)
        env_key = {"artificial_analysis": self._aa_env, "llm_stats": self._llm_env}
        options: list[dict] = []
        for source in QUALITY_SOURCES:
            has_key = not source.requires_key or (
                status.get(source.id, False) or bool(env_key.get(source.id))
            )
            options.append(
                {
                    "id": source.id,
                    "label": source.label,
                    "requires_key": source.requires_key,
                    "has_key": has_key,
                }
            )
        return options

    def invalidate_catalog(self) -> None:
        """Drop the cached catalog so the next request rebuilds with current credentials
        (called when an outbound credential changes)."""
        self._catalog.invalidate()

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
