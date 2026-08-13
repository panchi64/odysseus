"""Calendar surface (`CAL-1..3`) — **reserved stub**, filled in by the calendar track (T2).

See ``routes/mail.py`` for why the surface is registered before it exists.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/calendar", tags=["calendar"])
