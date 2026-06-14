"""Cookbook surface — host hardware + the models compatible with it.

Thin: detect/refresh the hardware profile and rank the catalog models that run on it
(the detected host, or an operator-supplied *simulated* profile for the what-if). The
list is ranked by fit + live quality, never a curated recommendation. An unsourceable
catalog degrades to an empty list with an explicit ``available=False`` flag — never a
fabricated list, never a 500.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from core.exceptions import DegradedCapabilityError
from routes import deps
from services.cookbook import CompatibleModel, HardwareProfile

router = APIRouter(prefix="/models/cookbook", tags=["cookbook"])


class CompatibleModels(BaseModel):
    models: list[CompatibleModel]
    # False when the live catalog couldn't be sourced (offline, no cache yet).
    available: bool


@router.get("/hardware", response_model=HardwareProfile)
async def get_hardware(request: Request) -> HardwareProfile:
    return await deps.cookbook(request).detect()


@router.post("/hardware/refresh", response_model=HardwareProfile)
async def refresh_hardware(request: Request) -> HardwareProfile:
    return await deps.cookbook(request).refresh()


@router.get("/compatible", response_model=CompatibleModels)
async def get_compatible(request: Request) -> CompatibleModels:
    try:
        models = await deps.cookbook(request).compatible_models()
    except DegradedCapabilityError:
        return CompatibleModels(models=[], available=False)
    return CompatibleModels(models=models, available=True)


@router.get("/search", response_model=CompatibleModels)
async def search_models(request: Request, q: str = "") -> CompatibleModels:
    query = q.strip()
    if not query:
        return CompatibleModels(models=[], available=True)
    try:
        models = await deps.cookbook(request).search(query)
    except DegradedCapabilityError:
        return CompatibleModels(models=[], available=False)
    return CompatibleModels(models=models, available=True)


@router.post("/compatible", response_model=CompatibleModels)
async def simulate_compatible(profile: HardwareProfile, request: Request) -> CompatibleModels:
    # Score against the supplied hardware, marked as a simulation (the what-if path).
    simulated = profile.model_copy(update={"simulated": True, "source": "simulated"})
    try:
        models = await deps.cookbook(request).compatible_models(simulated)
    except DegradedCapabilityError:
        return CompatibleModels(models=[], available=False)
    return CompatibleModels(models=models, available=True)
