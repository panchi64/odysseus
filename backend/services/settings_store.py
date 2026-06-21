"""Owner-scoped key/value operator preferences over the ``AppSetting`` table.

A tiny persisted store for small, non-secret preferences that don't warrant a bespoke
table (the local models directory is the first). Plain strings — structured/secret
config still lives in ``core/config.py`` (env) and the vault. Owner-scoped like every
record, so a per-user split later needs no rewrite.
"""

from __future__ import annotations

from sqlalchemy import Engine
from sqlmodel import Session, select

from core.db import in_session
from models._fields import utcnow
from models.app_setting import AppSetting


class SettingsStore:
    def __init__(self, db_engine: Engine) -> None:
        self._db = db_engine

    async def get(self, owner_id: str, key: str, default: str | None = None) -> str | None:
        def work(session: Session) -> str | None:
            row = session.exec(
                select(AppSetting)
                .where(AppSetting.owner_id == owner_id)
                .where(AppSetting.key == key)
            ).first()
            return row.value if row is not None else default

        return await in_session(self._db, work)

    async def set(self, owner_id: str, key: str, value: str) -> None:
        """Upsert one (owner, key) preference."""

        def work(session: Session) -> None:
            row = session.exec(
                select(AppSetting)
                .where(AppSetting.owner_id == owner_id)
                .where(AppSetting.key == key)
            ).first()
            if row is None:
                session.add(AppSetting(owner_id=owner_id, key=key, value=value))
            else:
                row.value = value
                row.updated_at = utcnow()
                session.add(row)

        await in_session(self._db, work)
