"""Backup & restore (`BACKUP-1..2`) — **reserved stub**, filled in by the vault/backup
track (T4).

See ``routes/mail.py`` for why the surface is registered before it exists.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/backup", tags=["backup"])
