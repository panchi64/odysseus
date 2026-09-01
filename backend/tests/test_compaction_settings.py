"""Compaction defaults and the operator's dials over them.

Three things are worth pinning here, because each of them silently changes when a fold
happens or how much of the thread survives it:

- **The config defaults.** 80% (not 95%, which folds with no room left for the turn that
  triggered the fold), 3 retained exchanges (not 0), a summarizer input ceiling of 32k, and
  a summarizer timeout *below* the inactivity watchdog — a summarizer allowed to run as
  long as the watchdog would let the watchdog kill the run it was trying to save.
- **``keep_turns`` as a stored preference**, where 0 is a choice and not an absent value —
  the failure mode of a truthiness test is that "keep nothing" silently reads as "keep the
  default 3", so it is tested in both directions.
- **The round-trip through ``PUT /chat/settings``**, including the bounds and the rule that
  a body touching one field of the group leaves the others alone.
"""

from __future__ import annotations

import pytest

from agent.summarize import build_auto_compact_policy, resolve_auto_compact_policy
from core.config import Settings, get_settings
from core.db import init_db, make_engine
from services.settings_store import (
    AUTO_COMPACT_ENABLED_KEY,
    AUTO_COMPACT_KEEP_TURNS_KEY,
    AUTO_COMPACT_KEEP_TURNS_MAX,
    AUTO_COMPACT_THRESHOLD_KEY,
    AutoCompactSettings,
    SettingsStore,
    get_auto_compact,
    set_auto_compact,
)

from ._helpers import client_app

OWNER = "op"


def _store() -> SettingsStore:
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    return SettingsStore(engine)


# --- config defaults ---------------------------------------------------------


def test_the_compaction_defaults():
    cfg = Settings()
    assert cfg.auto_compact_enabled is True
    assert cfg.auto_compact_threshold == pytest.approx(0.80)
    assert cfg.auto_compact_keep_turns == 3
    assert cfg.auto_compact_input_max_tokens == 32000


def test_the_summarizer_timeout_sits_below_the_inactivity_watchdog():
    """A summarizer allowed to run as long as the watchdog is a summarizer that can get the
    run it was saving killed mid-fold."""
    cfg = Settings()
    assert cfg.run_inactivity_timeout_s is not None
    assert cfg.auto_compact_timeout_s < cfg.run_inactivity_timeout_s


def test_the_overhead_fallback_is_not_zero():
    """A thread whose turns predate the per-thread overhead record must not be told it has
    a free 14k of instructions and tool schemas."""
    assert Settings().context_overhead_fallback_tokens > 0


def test_the_anthropic_cache_ttl_default():
    assert Settings().anthropic_cache_ttl == "5m"


# --- the store ---------------------------------------------------------------


async def test_keep_turns_falls_back_to_the_config_default_when_unset():
    assert (await get_auto_compact(_store(), OWNER)).keep_turns == (
        get_settings().auto_compact_keep_turns
    )


async def test_keep_turns_round_trips_through_the_store():
    store = _store()
    stored = await set_auto_compact(
        store, OWNER, AutoCompactSettings(enabled=True, threshold=0.7, keep_turns=6)
    )
    assert stored.keep_turns == 6
    read = await get_auto_compact(store, OWNER)
    assert (read.enabled, read.threshold, read.keep_turns) == (True, 0.7, 6)


async def test_zero_keep_turns_is_a_choice_not_an_absent_value():
    """The failure mode a truthiness test would introduce: "keep nothing" reading back as
    the config default. 0 means the summary *is* the whole replay."""
    store = _store()
    await set_auto_compact(
        store, OWNER, AutoCompactSettings(enabled=True, threshold=0.8, keep_turns=0)
    )
    assert (await get_auto_compact(store, OWNER)).keep_turns == 0


@pytest.mark.parametrize("bad", ["not-a-number", "-1", str(AUTO_COMPACT_KEEP_TURNS_MAX + 1)])
async def test_a_corrupt_or_out_of_range_keep_turns_falls_back(bad: str):
    store = _store()
    await store.set(OWNER, AUTO_COMPACT_KEEP_TURNS_KEY, bad)
    assert (await get_auto_compact(store, OWNER)).keep_turns == (
        get_settings().auto_compact_keep_turns
    )


# --- policy resolution -------------------------------------------------------


def test_the_policy_takes_a_keep_turns_override_including_zero():
    assert build_auto_compact_policy(Settings(), keep_turns=7).keep_turns == 7
    assert build_auto_compact_policy(Settings(), keep_turns=0).keep_turns == 0
    assert build_auto_compact_policy(Settings()).keep_turns == 3


async def test_the_resolved_policy_carries_the_stored_keep_turns():
    """The engine reads the policy, never the store — so the operator's dial has to arrive
    through this resolution or it does nothing at all."""
    store = _store()
    await store.set(OWNER, AUTO_COMPACT_KEEP_TURNS_KEY, "5")
    await store.set(OWNER, AUTO_COMPACT_THRESHOLD_KEY, "0.6")
    policy = await resolve_auto_compact_policy(store, OWNER)
    assert policy.keep_turns == 5
    assert policy.threshold == pytest.approx(0.6)


async def test_the_per_conversation_override_still_wins_on_enablement():
    store = _store()
    await store.set(OWNER, AUTO_COMPACT_ENABLED_KEY, "true")
    await store.set(OWNER, AUTO_COMPACT_KEEP_TURNS_KEY, "2")
    policy = await resolve_auto_compact_policy(store, OWNER, override=False)
    assert policy.enabled is False
    assert policy.keep_turns == 2


# --- the route ---------------------------------------------------------------


async def test_chat_settings_expose_and_round_trip_keep_turns():
    async with client_app() as (client, _app):
        got = (await client.get("/chat/settings")).json()
        assert got["auto_compact_keep_turns"] == get_settings().auto_compact_keep_turns

        put = await client.put("/chat/settings", json={"auto_compact_keep_turns": 0})
        assert put.status_code == 200
        assert put.json()["auto_compact_keep_turns"] == 0
        again = (await client.get("/chat/settings")).json()
        assert again["auto_compact_keep_turns"] == 0


async def test_a_put_touching_only_keep_turns_leaves_the_group_alone():
    async with client_app() as (client, _app):
        await client.put(
            "/chat/settings",
            json={"auto_compact_enabled": False, "auto_compact_threshold": 0.6},
        )
        body = (await client.put("/chat/settings", json={"auto_compact_keep_turns": 4})).json()
        assert body["auto_compact_keep_turns"] == 4
        assert body["auto_compact_enabled"] is False
        assert body["auto_compact_threshold"] == pytest.approx(0.6)


async def test_a_put_touching_only_the_threshold_leaves_keep_turns_alone():
    async with client_app() as (client, _app):
        await client.put("/chat/settings", json={"auto_compact_keep_turns": 9})
        body = (await client.put("/chat/settings", json={"auto_compact_threshold": 0.5})).json()
        assert body["auto_compact_keep_turns"] == 9


@pytest.mark.parametrize("bad", [-1, AUTO_COMPACT_KEEP_TURNS_MAX + 1, 1.5])
async def test_an_out_of_range_keep_turns_is_rejected(bad: float):
    """Below 0 is meaningless; above the ceiling the fold would retain the whole thread and
    free no room at the moment the thread has none."""
    async with client_app() as (client, _app):
        resp = await client.put("/chat/settings", json={"auto_compact_keep_turns": bad})
        assert resp.status_code == 422
