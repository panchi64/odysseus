"""Owner-scoped settings store — the compaction getters' corruption-safety + batched read."""

from __future__ import annotations

from core.config import get_settings
from core.db import init_db, make_engine
from services.settings_store import (
    COMPACTION_ENABLED_KEY,
    COMPACTION_KEEP_RECENT_KEY,
    COMPACTION_MIN_TOKENS_KEY,
    INACTIVITY_TIMEOUT_KEY,
    SettingsStore,
    get_compaction,
    get_inactivity_timeout,
    resolve_compaction_enabled,
    set_inactivity_timeout,
)

OWNER = "op"


def _store() -> SettingsStore:
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    return SettingsStore(engine)


async def test_get_many_reads_several_keys_in_one_call():
    store = _store()
    await store.set(OWNER, COMPACTION_KEEP_RECENT_KEY, "4")
    await store.set(OWNER, COMPACTION_MIN_TOKENS_KEY, "900")

    values = await store.get_many(
        OWNER, (COMPACTION_ENABLED_KEY, COMPACTION_KEEP_RECENT_KEY, COMPACTION_MIN_TOKENS_KEY)
    )
    assert values == {COMPACTION_KEEP_RECENT_KEY: "4", COMPACTION_MIN_TOKENS_KEY: "900"}
    # An absent key is simply omitted — the caller applies its own default.
    assert COMPACTION_ENABLED_KEY not in values


async def test_get_compaction_uses_config_defaults_when_unset():
    store = _store()
    cfg = get_settings()
    cs = await get_compaction(store, OWNER)
    assert cs.enabled == cfg.compaction_enabled
    assert cs.keep_recent == cfg.compaction_keep_recent
    assert cs.min_tokens == cfg.compaction_min_tokens


async def test_get_compaction_round_trips_overrides():
    store = _store()
    await store.set(OWNER, COMPACTION_ENABLED_KEY, "false")
    await store.set(OWNER, COMPACTION_KEEP_RECENT_KEY, "2")
    await store.set(OWNER, COMPACTION_MIN_TOKENS_KEY, "1500")

    cs = await get_compaction(store, OWNER)
    assert cs.enabled is False and cs.keep_recent == 2 and cs.min_tokens == 1500


async def test_corrupted_enabled_flag_falls_back_to_the_config_default():
    # A stored value that is neither "true" nor "false" (legacy/corrupt/case-variant) must fall
    # back to the config default — not silently read as False the way a bare `== "true"` would.
    store = _store()
    await store.set(OWNER, COMPACTION_ENABLED_KEY, "True")  # wrong case
    cs = await get_compaction(store, OWNER)
    assert cs.enabled == get_settings().compaction_enabled


async def test_corrupted_int_fields_fall_back_to_the_config_default():
    store = _store()
    cfg = get_settings()
    await store.set(OWNER, COMPACTION_KEEP_RECENT_KEY, "not-a-number")
    await store.set(OWNER, COMPACTION_MIN_TOKENS_KEY, "-5")  # negative ⇒ default
    cs = await get_compaction(store, OWNER)
    assert cs.keep_recent == cfg.compaction_keep_recent
    assert cs.min_tokens == cfg.compaction_min_tokens


def test_resolve_compaction_enabled_precedence():
    # null override ⇒ inherit the global; a concrete override wins either way.
    assert resolve_compaction_enabled(None, True) is True
    assert resolve_compaction_enabled(None, False) is False
    assert resolve_compaction_enabled(False, True) is False
    assert resolve_compaction_enabled(True, False) is True


async def test_get_inactivity_timeout_uses_config_default_when_unset():
    store = _store()
    assert await get_inactivity_timeout(store, OWNER) == get_settings().run_inactivity_timeout_s


async def test_inactivity_timeout_round_trips_an_override():
    store = _store()
    stored = await set_inactivity_timeout(store, OWNER, 300.0)
    assert stored == 300.0
    assert await get_inactivity_timeout(store, OWNER) == 300.0


async def test_corrupted_inactivity_timeout_falls_back_to_the_config_default():
    # A stored 0, negative, or non-numeric value must fall back to the config default
    # rather than silently disabling the watchdog (0) or reading as a nonsense bound.
    store = _store()
    cfg = get_settings()
    await store.set(OWNER, INACTIVITY_TIMEOUT_KEY, "0")
    assert await get_inactivity_timeout(store, OWNER) == cfg.run_inactivity_timeout_s
    await store.set(OWNER, INACTIVITY_TIMEOUT_KEY, "-5")
    assert await get_inactivity_timeout(store, OWNER) == cfg.run_inactivity_timeout_s
    await store.set(OWNER, INACTIVITY_TIMEOUT_KEY, "not-a-number")
    assert await get_inactivity_timeout(store, OWNER) == cfg.run_inactivity_timeout_s
