"""Mail surface (`EMAIL-1..5`) — **reserved stub**, filled in by the mail track (T1).

Registered in ``app.py`` from this commit so the six parallel sprint tracks never contend
for the router-registration block. The track that owns this surface adds its endpoints
here and touches no shared file.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/mail", tags=["mail"])
