"""Cookbook surface — host hardware detection.

Thin: detect/refresh the host hardware profile (the real, working signal). The profile
is probed on the host and cached; ``refresh`` re-probes after a hardware change.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from routes import deps
from services.cookbook import HardwareProfile

router = APIRouter(prefix="/models/cookbook", tags=["cookbook"])


@router.get("/hardware", response_model=HardwareProfile)
async def get_hardware(request: Request) -> HardwareProfile:
    return await deps.cookbook(request).detect()


@router.post("/hardware/refresh", response_model=HardwareProfile)
async def refresh_hardware(request: Request) -> HardwareProfile:
    return await deps.cookbook(request).refresh()
