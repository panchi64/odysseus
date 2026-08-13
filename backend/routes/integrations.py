"""Third-party connectors (`INTEG-1..3`) — **reserved stub**, filled in by the external
tools track (T3), which owns it alongside ``routes/mcp.py`` because both ride the one
`AE-3.6` per-tool trust mechanism.

See ``routes/mail.py`` for why the surface is registered before it exists.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/integrations", tags=["integrations"])
