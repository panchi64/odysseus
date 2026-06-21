"""CookbookService — the capability facade the router talks to.

Host hardware detection: the host profile is probed once and cached behind a lock
(concurrent first-callers collapse to one probe); `refresh()` re-probes after a hardware
change. Download/serve (the rest of the Cookbook) build on this package as they land.
"""

from __future__ import annotations

import asyncio
import logging

from . import hardware
from .models import HardwareProfile

logger = logging.getLogger(__name__)


class CookbookService:
    def __init__(self) -> None:
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

    async def warmup(self) -> None:
        """Best-effort background priming at boot — probe the hardware so the first
        request is cache-served. A slow probe must not break startup, so a failure is
        logged, not raised."""
        try:
            await self.detect()
        except Exception:
            logger.warning("cookbook: hardware warm-up failed", exc_info=True)
