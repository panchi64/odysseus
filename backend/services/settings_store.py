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

# Conversation auto-compaction (agent/summarize.py) — the product's one context reduction:
# whether to fold a thread's older turns into a utility-model summary once its footprint
# reaches `threshold` of the model's context window, expressed as a fraction (0.95 = 95%).
# The retained-turn count is config-only; these two are what the operator actually tunes.
AUTO_COMPACT_ENABLED_KEY = "chat.auto_compact_enabled"
AUTO_COMPACT_THRESHOLD_KEY = "chat.auto_compact_threshold"

# The agent's per-turn model-request ceiling (agent/engine.py's `UsageLimits`): the
# operator's runtime override of `agent_request_limit`. Every model round-trip spends
# one, so this is what a tool-heavy turn actually runs out of.
AGENT_REQUEST_LIMIT_KEY = "chat.agent_request_limit"

# The run substrate's inactivity watchdog (runs/registry.py): the operator's runtime
# override of `run_inactivity_timeout_s` — how long a run may go without emitting an
# event before it is stopped. Long generations (a big file write, a slow first token)
# need more than the 120s default, so this is what the operator tunes to keep a turn
# alive. Seconds; the config default (or None = disabled) applies when unset.
INACTIVITY_TIMEOUT_KEY = "chat.inactivity_timeout_s"

# Offline mode (services/offline.py) persists the operator's two switches here as
# "true"/"false" strings: the manual force-offline toggle and the auto-detect master
# switch. Policy, not a secret — stored in the clear like every other app preference.
OFFLINE_MANUAL_KEY = "offline.manual"
OFFLINE_AUTO_KEY = "offline.auto"

# The operator's disabled-tool set (services/tool_policy.py, AE-3.3), stored as a JSON
# list of namespaced tool names. Policy, not content — in the clear like the rest.
DISABLED_TOOLS_KEY = "tools.disabled"


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
        of related keys (e.g. auto-compaction's pair) without paying a round-trip per key.
        Absent keys are simply omitted from the result; the caller applies its own defaults.

        Only the keys asked for are read, so a key this codebase no longer knows about is
        inert: a retired setting's row can be left in place rather than migrated away."""

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


async def get_agent_request_limit(store: SettingsStore, owner_id: str) -> int:
    """The operator's per-turn model-request ceiling — the runtime override if set (and
    valid), else the config default. Unlike the token caps this one is floored at 1, not
    0: a turn allowed zero model requests could never answer at all, so a stored 0 (or a
    corrupted value) falls back to the default rather than bricking every turn."""
    raw = await store.get(owner_id, AGENT_REQUEST_LIMIT_KEY)
    return _positive_int_or(raw, get_settings().agent_request_limit)


async def set_agent_request_limit(store: SettingsStore, owner_id: str, value: int) -> int:
    """Persist the operator's per-turn model-request ceiling. Returns the stored value.
    The ``ge=1`` body field at the route is what rejects a nonsensical one; a stray
    sub-1 value stored here would simply be ignored by the getter."""
    await store.set(owner_id, AGENT_REQUEST_LIMIT_KEY, str(value))
    return value


async def get_inactivity_timeout(store: SettingsStore, owner_id: str) -> float | None:
    """The operator's inactivity timeout in seconds — the runtime override if set (and
    valid), else the config default. The default may itself be ``None`` (watchdog
    disabled), which is a meaningful value to return, not a corruption. A stored 0,
    negative, or non-numeric value falls back to the default rather than disabling the
    watchdog by accident."""
    raw = await store.get(owner_id, INACTIVITY_TIMEOUT_KEY)
    return _positive_float_or(raw, get_settings().run_inactivity_timeout_s)


async def set_inactivity_timeout(
    store: SettingsStore, owner_id: str, value: float
) -> float:
    """Persist the operator's inactivity timeout in seconds. Returns the stored value.
    The ``gt=0`` body field at the route rejects a nonsensical one; a stray non-positive
    value stored here would simply be ignored by the getter."""
    await store.set(owner_id, INACTIVITY_TIMEOUT_KEY, str(value))
    return value


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


def _positive_int_or(raw: str | None, default: int) -> int:
    """:func:`_int_or` for a setting where 0 is meaningless rather than merely minimal —
    the floor is 1, so a stored 0 falls back to the default like any other bad value."""
    value = _int_or(raw, default)
    return value if value >= 1 else default


@dataclass(frozen=True)
class AutoCompactSettings:
    """The operator's effective conversation auto-compaction preferences. ``threshold`` is
    a fraction of the model's context window, not a percentage — the UI presents it as one,
    but the wire and the store carry the same 0–1 quantity the context meter already uses."""

    enabled: bool
    threshold: float


def _float_or(raw: str | None, default: float) -> float:
    """A float in ``(0, 1]`` from a stored string, else the default — :func:`_int_or` for
    the one setting that is a fraction. Both bounds matter: 0 (or a negative) would fire
    compaction on an empty thread, and above 1 it could never fire at all, so a corrupted
    value falls back rather than silently disabling or thrashing the feature."""
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if 0 < value <= 1 else default


def _positive_float_or(raw: str | None, default: float | None) -> float | None:
    """A positive float (seconds) from a stored string, else the default — the
    :func:`_float_or` counterpart for a setting whose value is unbounded above and whose
    default may legitimately be ``None`` (the watchdog disabled). A stored 0, negative, or
    non-numeric value falls back to the default rather than silently disabling a bound."""
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


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


async def get_auto_compact(store: SettingsStore, owner_id: str) -> AutoCompactSettings:
    """The operator's effective conversation auto-compaction settings — runtime overrides
    where set (and valid), else the config defaults. One batched read for the pair."""
    cfg = get_settings()
    values = await store.get_many(
        owner_id, (AUTO_COMPACT_ENABLED_KEY, AUTO_COMPACT_THRESHOLD_KEY)
    )
    return AutoCompactSettings(
        enabled=_bool_or(values.get(AUTO_COMPACT_ENABLED_KEY), cfg.auto_compact_enabled),
        threshold=_float_or(values.get(AUTO_COMPACT_THRESHOLD_KEY), cfg.auto_compact_threshold),
    )


async def set_auto_compact(
    store: SettingsStore, owner_id: str, settings: AutoCompactSettings
) -> AutoCompactSettings:
    """Persist the operator's auto-compaction preferences. Returns the stored settings."""
    await store.set(
        owner_id, AUTO_COMPACT_ENABLED_KEY, "true" if settings.enabled else "false"
    )
    await store.set(owner_id, AUTO_COMPACT_THRESHOLD_KEY, str(settings.threshold))
    return settings
