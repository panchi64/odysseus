"""External MCP tool servers (`MCP-1..3`) — **reserved stub**, filled in by the external
tools track (T3).

See ``routes/mail.py`` for why the surface is registered before it exists.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/mcp", tags=["mcp"])
