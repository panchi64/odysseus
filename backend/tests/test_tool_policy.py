"""`AE-3.3` — the operator disabling individual tools, end to end.

The enabled gate itself is covered by ``test_tools.py`` (hand a run a disabled set, watch
the tool vanish). What is tested here is the half that makes the requirement real: the
operator's persisted set, the catalog they choose from, and — the part that has silently
regressed before — that the set actually reaches **every** path a turn is composed on,
composing with offline mode's automatic web suspension rather than replacing it.
"""

from __future__ import annotations

import asyncio
import json

from pydantic_ai import FunctionToolset, RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

import routes.chat as chat_routes
import routes.runs as runs_routes
import tools.toolsets as toolsets
from core.db import init_db, make_engine
from runs import Run, RunStream
from services.registry import ModelRegistry, ResolvedModel
from services.settings_store import DISABLED_TOOLS_KEY, SettingsStore
from services.tool_policy import (
    effective_disabled_tools,
    get_disabled_tools,
    set_tool_enabled,
)
from tools import RunDeps, build_agent_toolsets
from tools.catalog import tool_catalog

from ._helpers import client_app, patch_model_resolution

OWNER = "operator"


def _store() -> SettingsStore:
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    return SettingsStore(engine)


async def _agent_visible(disabled: frozenset[str]) -> set[str]:
    """The tool names a real run would actually be offered, resolved through the same
    composed toolset stack the engine hands the Agent — not a re-derivation of the naming
    rule, so this is the ground truth the catalog is measured against."""
    run = Run(id="t", kind="chat", owner_id=OWNER, stream=RunStream())
    deps = RunDeps(run=run, owner_id=OWNER, disabled_tools=disabled)
    ctx = RunContext(deps=deps, model=TestModel(), usage=RunUsage())
    return set(await build_agent_toolsets()[0].get_tools(ctx))


# --- the catalog is the agent's own, not a hand-maintained list ----------------------


async def test_catalog_matches_the_names_the_agent_is_offered():
    # Pins the namespacing convention (`category_tool`) against what Pydantic AI's
    # prefixing actually produces: if the library ever changed it, every toggle in the
    # settings screen would quietly stop matching, and this fails instead.
    assert {t.name for t in tool_catalog()} == await _agent_visible(frozenset())


async def test_catalog_carries_category_and_description():
    now = next(t for t in tool_catalog() if t.name == "builtin_now")
    assert now.category == "builtin"
    assert "UTC" in now.description


# --- the operator's set actually hides the tool --------------------------------------


async def test_operator_disabled_tool_is_absent_from_the_catalog_the_agent_sees():
    store = _store()
    await set_tool_enabled(store, OWNER, "builtin_now", False)
    disabled = await get_disabled_tools(store, OWNER)
    visible = await _agent_visible(disabled)
    assert "builtin_now" not in visible
    assert "builtin_expand_tool_result" in visible  # only the named tool goes


async def test_flip_round_trips_and_persists():
    store = _store()
    await set_tool_enabled(store, OWNER, "memory_recall", False)
    assert await get_disabled_tools(store, OWNER) == {"memory_recall"}
    await set_tool_enabled(store, OWNER, "memory_recall", True)
    assert await get_disabled_tools(store, OWNER) == frozenset()


async def test_a_corrupt_stored_value_reads_as_nothing_disabled():
    # Fail open: a mangled preference must not take the whole catalog away from the agent.
    store = _store()
    await store.set(OWNER, DISABLED_TOOLS_KEY, "{not json")
    assert await get_disabled_tools(store, OWNER) == frozenset()
    await store.set(OWNER, DISABLED_TOOLS_KEY, json.dumps({"memory_recall": True}))
    assert await get_disabled_tools(store, OWNER) == frozenset()


# --- the two sources compose ---------------------------------------------------------


class _StubOffline:
    def __init__(self, disabled: frozenset[str]) -> None:
        self._disabled = disabled

    def web_tools_disabled(self) -> frozenset[str]:
        return self._disabled


async def test_operator_and_offline_sets_union_rather_than_overwrite():
    store = _store()
    await set_tool_enabled(store, OWNER, "builtin_now", False)
    offline = _StubOffline(frozenset({"web_search", "web_fetch"}))
    assert await effective_disabled_tools(store, offline, OWNER) == {
        "builtin_now",
        "web_search",
        "web_fetch",
    }


async def test_offline_alone_still_applies_with_no_operator_choices():
    store = _store()
    offline = _StubOffline(frozenset({"web_search"}))
    assert await effective_disabled_tools(store, offline, OWNER) == {"web_search"}


def _force_offline(monkeypatch, app, *names: str) -> None:
    """Pin the live offline service's automatic set without swapping the service out —
    the lifespan still owns its shutdown."""
    monkeypatch.setattr(
        app.state.offline, "web_tools_disabled", lambda: frozenset(names)
    )


# --- the route -----------------------------------------------------------------------


async def test_route_lists_the_catalog_with_enabled_state():
    async with client_app() as (client, _app):
        rows = (await client.get("/tools")).json()
        assert {r["name"] for r in rows} == {t.name for t in tool_catalog()}
        assert all(r["enabled"] for r in rows)

        resp = await client.put("/tools/builtin_now", json={"enabled": False})
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

        rows = (await client.get("/tools")).json()
        assert next(r for r in rows if r["name"] == "builtin_now")["enabled"] is False
        assert next(r for r in rows if r["name"] == "memory_recall")["enabled"] is True


async def test_route_rejects_an_unknown_tool_name():
    async with client_app() as (client, _app):
        resp = await client.put("/tools/not_a_tool", json={"enabled": False})
        assert resp.status_code == 404


async def test_chat_turn_composes_with_the_operator_set(monkeypatch):
    async with client_app() as (client, app):
        await client.put("/tools/builtin_now", json={"enabled": False})
        _force_offline(monkeypatch, app, "web_search")

        captured: dict[str, frozenset[str]] = {}
        real = chat_routes.compose_turn

        def spy(**kwargs):
            captured["disabled"] = kwargs["disabled_tools"]
            return real(**kwargs)

        monkeypatch.setattr(chat_routes, "compose_turn", spy)
        patch_model_resolution(monkeypatch)
        await client.post("/chat", json={"prompt": "hi"})

    assert captured["disabled"] == {"builtin_now", "web_search"}


# --- the approval-resume path, specifically ------------------------------------------


def _install_sensitive_tool(monkeypatch):
    """A TestModel plus one approval-required tool, so a turn parks — the only state from
    which the resume path runs. Mirrors ``test_approval_routes``' own fixture."""

    async def fake_resolve(self, role, **kwargs):
        return TestModel(custom_output_text="done")

    async def fake_resolve_detailed(self, role, **kwargs):
        return ResolvedModel(model=TestModel(custom_output_text="done"), reasoning_off={})

    def danger_categories():
        toolset: FunctionToolset[RunDeps] = FunctionToolset()

        @toolset.tool_plain(requires_approval=True)
        def delete_thing(name: str) -> str:
            return f"deleted {name}"

        @toolset.tool_plain
        def safe_thing() -> str:
            return "safe"

        return {"danger": toolset}

    monkeypatch.setattr(ModelRegistry, "resolve", fake_resolve)
    monkeypatch.setattr(ModelRegistry, "resolve_detailed", fake_resolve_detailed)
    monkeypatch.setattr(toolsets, "default_categories", danger_categories)


async def _await_parked(app, run_id):
    for _ in range(200):
        run = app.state.runs.get(run_id)
        if run is not None and run.status == "awaiting_input":
            return run
        await asyncio.sleep(0.01)
    raise AssertionError("run never parked")


async def test_resume_applies_the_operator_set_and_the_offline_set(monkeypatch):
    """The approval-resume path is where a sensitive tool actually executes, and it has
    dropped run state before — so assert directly that both sources reach the resumed
    turn's deps, including a tool the operator switched off *while it was parked*."""
    _install_sensitive_tool(monkeypatch)
    async with client_app() as (client, app):
        run_id = (await client.post("/chat", json={"prompt": "delete it"})).json()["run_id"]
        run = await _await_parked(app, run_id)

        # Switched off after the turn parked: the resume must pick up the current policy,
        # not whatever was in force when the run started.
        await client.put("/tools/danger_safe_thing", json={"enabled": False})
        _force_offline(monkeypatch, app, "web_search")

        captured: dict[str, frozenset[str]] = {}
        real = runs_routes.build_resume_orchestrator

        def spy(*args, **kwargs):
            captured["disabled"] = kwargs["disabled_tools"]
            return real(*args, **kwargs)

        monkeypatch.setattr(runs_routes, "build_resume_orchestrator", spy)

        call_id = run.parked_payload.requests.approvals[0].tool_call_id
        resp = await client.post(
            f"/runs/{run_id}/approve",
            json={"decisions": [{"tool_call_id": call_id, "approved": True}]},
        )
        assert resp.status_code == 202

    assert captured["disabled"] == {"danger_safe_thing", "web_search"}
