"""Owner-scoped key/value settings — a tiny persisted store for small operator prefs.

The first consumer is the Cookbook's active quality source. Values are plain strings (not
secret, so no vault); structured config still lives in ``core/config.py``. Raises nothing
— a missing key returns the caller's default.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Engine
from sqlmodel import Session, select

from core.db import in_session
from models.app_setting import AppSetting


class SettingsStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    async def get(self, owner_id: str, key: str) -> str | None:
        def work(session: Session) -> str | None:
            row = session.exec(
                select(AppSetting).where(
                    AppSetting.owner_id == owner_id, AppSetting.key == key
                )
            ).first()
            return row.value if row is not None else None

        return await in_session(self._engine, work)

    async def set(self, owner_id: str, key: str, value: str) -> None:
        def work(session: Session) -> None:
            row = session.exec(
                select(AppSetting).where(
                    AppSetting.owner_id == owner_id, AppSetting.key == key
                )
            ).first()
            if row is None:
                row = AppSetting(owner_id=owner_id, key=key, value=value)
            else:
                row.value = value
                row.updated_at = datetime.now(UTC)
            session.add(row)
            session.flush()

        await in_session(self._engine, work)
