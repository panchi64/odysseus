"""Owner-scoped key/value operator preferences over the ``AppSetting`` table.

A tiny persisted store for small, non-secret preferences that don't warrant a bespoke
table (the local models directory is the first). Plain strings — structured/secret
config still lives in ``core/config.py`` (env) and the vault. Owner-scoped like every
record, so a per-user split later needs no rewrite.
"""

from __future__ import annotations

from sqlalchemy import Engine
from sqlmodel import Session, select

from core.config import get_settings
from core.db import in_session
from models._fields import utcnow
from models.app_setting import AppSetting

# The owner-scoped key the chat attachment inline token cap is stored under.
ATTACHMENT_INLINE_MAX_TOKENS_KEY = "chat.attachment_inline_max_tokens"

# Offline mode (services/offline.py) persists the operator's two switches here as
# "true"/"false" strings: the manual force-offline toggle and the auto-detect master
# switch. Policy, not a secret — stored in the clear like every other app preference.
OFFLINE_MANUAL_KEY = "offline.manual"
OFFLINE_AUTO_KEY = "offline.auto"


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


async def get_attachment_inline_max_tokens(store: SettingsStore, owner_id: str) -> int:
    """The operator's chat attachment inline token cap — the runtime override if set
    (and valid), else the config default. A non-numeric or negative stored value is
    ignored in favour of the default, so a corrupted setting can't disable retention."""
    raw = await store.get(owner_id, ATTACHMENT_INLINE_MAX_TOKENS_KEY)
    if raw is not None:
        try:
            value = int(raw)
        except ValueError:
            value = -1
        if value >= 0:
            return value
    return get_settings().attachment_inline_max_tokens


async def set_attachment_inline_max_tokens(
    store: SettingsStore, owner_id: str, value: int
) -> int:
    """Persist the operator's inline token cap. Returns the stored value. Non-negativity
    is enforced at the route (the `ge=0` body field); a stray negative stored here would
    simply be ignored by the getter, which falls back to the default."""
    await store.set(owner_id, ATTACHMENT_INLINE_MAX_TOKENS_KEY, str(value))
    return value
