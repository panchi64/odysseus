"""Scoped API tokens (`AUTH-4`) — **reserved stub**, filled in by the platform track (T6).

**Inbound** auth: tokens issued to clients for programmatic access, scoped and revocable.
Deliberately separate from ``routes/api_tokens.py`` (prefix ``/credentials``), which holds
the **outbound** third-party service keys the system calls other services with.

See ``routes/mail.py`` for why the surface is registered before it exists.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/tokens", tags=["tokens"])
