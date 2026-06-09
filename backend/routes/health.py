"""Liveness endpoint — confirms the app is assembled and serving."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from core.config import get_settings

router = APIRouter(tags=["health"])


class Health(BaseModel):
    status: str
    version: str


@router.get("/health", response_model=Health)
async def health() -> Health:
    return Health(status="ok", version=get_settings().version)
