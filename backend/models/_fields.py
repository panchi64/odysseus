"""Shared SQLModel column defaults — one source for ids and timestamps.

Every entity needs an opaque primary key and creation/update timestamps; keeping
the factories here means a change (uuid scheme, tz handling) lands in one place
rather than drifting across the model files.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(UTC)
