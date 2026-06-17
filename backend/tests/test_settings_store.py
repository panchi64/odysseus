"""Owner-scoped key/value settings — roundtrip + upsert. No network."""

from __future__ import annotations

from core.db import init_db, make_engine
from services.settings_store import SettingsStore

OWNER = "operator"


def _store() -> SettingsStore:
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    return SettingsStore(engine)


async def test_missing_key_returns_none():
    assert await _store().get(OWNER, "cookbook.quality_source") is None


async def test_set_get_and_upsert():
    store = _store()
    await store.set(OWNER, "cookbook.quality_source", "artificial_analysis")
    assert await store.get(OWNER, "cookbook.quality_source") == "artificial_analysis"
    await store.set(OWNER, "cookbook.quality_source", "llm_stats")
    assert await store.get(OWNER, "cookbook.quality_source") == "llm_stats"
    # Keys are owner-scoped.
    assert await store.get("someone-else", "cookbook.quality_source") is None
