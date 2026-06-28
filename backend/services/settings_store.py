"""Owner-scoped key/value operator preferences over the ``AppSetting`` table.

A tiny persisted store for small, non-secret preferences that don't warrant a bespoke
table (the local models directory is the first). Plain strings — structured/secret
config still lives in ``core/config.py`` (env) and the vault. Owner-scoped like every
record, so a per-user split later needs no rewrite.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine
from sqlmodel import Session, select

from core.config import get_settings
from core.db import in_session
from models._fields import utcnow
from models.app_setting import AppSetting

# The owner-scoped key the chat attachment inline token cap is stored under.
ATTACHMENT_INLINE_MAX_TOKENS_KEY = "chat.attachment_inline_max_tokens"

# Tool-result compaction (agent/compaction.py): the operator's runtime overrides of the
# config defaults — whether to condense oversized prior-turn tool results for the model, the
# rolling window of newest results kept full, and the size floor below which nothing is touched.
COMPACTION_ENABLED_KEY = "chat.compaction_enabled"
COMPACTION_KEEP_RECENT_KEY = "chat.compaction_keep_recent"
COMPACTION_MIN_TOKENS_KEY = "chat.compaction_min_tokens"

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

    async def get_many(self, owner_id: str, keys: tuple[str, ...]) -> dict[str, str]:
        """Read several (owner, key) preferences in one query — for a getter that needs a group
        of related keys (e.g. compaction's three) without paying a round-trip per key. Absent
        keys are simply omitted from the result; the caller applies its own defaults."""

        def work(session: Session) -> dict[str, str]:
            rows = session.exec(
                select(AppSetting)
                .where(AppSetting.owner_id == owner_id)
                .where(AppSetting.key.in_(keys))  # type: ignore[attr-defined]
            ).all()
            return {row.key: row.value for row in rows}

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
    return _int_or(raw, get_settings().attachment_inline_max_tokens)


async def set_attachment_inline_max_tokens(
    store: SettingsStore, owner_id: str, value: int
) -> int:
    """Persist the operator's inline token cap. Returns the stored value. Non-negativity
    is enforced at the route (the `ge=0` body field); a stray negative stored here would
    simply be ignored by the getter, which falls back to the default."""
    await store.set(owner_id, ATTACHMENT_INLINE_MAX_TOKENS_KEY, str(value))
    return value


@dataclass(frozen=True)
class CompactionSettings:
    """The operator's effective tool-result compaction preferences."""

    enabled: bool
    keep_recent: int
    min_tokens: int


def _int_or(raw: str | None, default: int) -> int:
    """A non-negative int from a stored string, else the default (a corrupted value can't
    silently flip the setting to something nonsensical)."""
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= 0 else default


def _bool_or(raw: str | None, default: bool) -> bool:
    """``True``/``False`` from a stored ``"true"``/``"false"`` string, else the default — so a
    corrupted/legacy value falls back to the default instead of silently reading as ``False``
    (the failure mode of a bare ``raw == "true"``), mirroring :func:`_int_or`."""
    if raw == "true":
        return True
    if raw == "false":
        return False
    return default


def resolve_compaction_enabled(override: bool | None, global_enabled: bool) -> bool:
    """A conversation's effective compaction on/off: its stored override when set, else the
    operator's global default. The one place this precedence lives, so the per-thread toggle's
    displayed state and the turn's actual behavior can't drift apart."""
    return global_enabled if override is None else override


async def get_compaction(store: SettingsStore, owner_id: str) -> CompactionSettings:
    """The operator's effective compaction settings — runtime overrides where set (and
    valid), else the config defaults. One batched read for the three related keys."""
    cfg = get_settings()
    values = await store.get_many(
        owner_id, (COMPACTION_ENABLED_KEY, COMPACTION_KEEP_RECENT_KEY, COMPACTION_MIN_TOKENS_KEY)
    )
    return CompactionSettings(
        enabled=_bool_or(values.get(COMPACTION_ENABLED_KEY), cfg.compaction_enabled),
        keep_recent=_int_or(values.get(COMPACTION_KEEP_RECENT_KEY), cfg.compaction_keep_recent),
        min_tokens=_int_or(values.get(COMPACTION_MIN_TOKENS_KEY), cfg.compaction_min_tokens),
    )


async def set_compaction(
    store: SettingsStore, owner_id: str, settings: CompactionSettings
) -> CompactionSettings:
    """Persist the operator's compaction preferences. Returns the stored settings."""
    await store.set(owner_id, COMPACTION_ENABLED_KEY, "true" if settings.enabled else "false")
    await store.set(owner_id, COMPACTION_KEEP_RECENT_KEY, str(settings.keep_recent))
    await store.set(owner_id, COMPACTION_MIN_TOKENS_KEY, str(settings.min_tokens))
    return settings
