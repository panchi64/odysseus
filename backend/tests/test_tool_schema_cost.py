"""What the tool catalog costs before the model has read a single message.

Every tool the model is offered arrives as name + description + JSON schema, at the head
of every request, whether or not the turn goes anywhere near it. That is the one part of
the window nobody chose and nobody sees, so it is measured here — against the *real*
assembled catalog (core plus every manifest's export), through the same
``agent.overhead`` measurement the context gauge draws from, so this number and the one
the operator reads can never be two different numbers.

Where it stands, measured by these tests: the full catalog is ~52k characters — call it
~12.8k tokens — across 68 tools, of which the browser category alone is 18 tools and
~15.7k characters. A Plan-level turn is handed ~28k, because everything above `read` is
withheld outright rather than offered and refused.

Two things are pinned. A **ceiling**, so the catalog cannot drift upward unnoticed one
tool at a time — a failure here is not necessarily a bug, but it is always a decision
somebody should make deliberately. And the **narrowing**, so the withholding that makes
Plan cheap stays real: it is enforcement first and a saving second, and a regression
would be invisible from either side alone.
"""

from __future__ import annotations

from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from agent.overhead import measure_overhead
from core.db import init_db, make_engine
from core.text import CHARS_PER_TOKEN_JSON
from runs import Run, RunStream
from services.modes import MODES
from services.permissions import PERMISSION_LEVELS
from services.settings_store import SettingsStore
from services.tool_policy import effective_disabled_tools
from tools import RunDeps, build_agent_toolsets

from ._helpers import full_tool_categories

#: What the assembled catalog may cost, in characters of serialized schema. Set a little
#: above today's ~52k so an ordinary addition lands quietly and a category-sized one does
#: not. Characters rather than tokens for the same reason the measurement itself uses
#: them: no tokenizer, no provider, no drift.
CATALOG_CEILING_CHARS = 60_000


class _AllOnline:
    """Offline mode with nothing suspended — this file measures the catalog, not
    connectivity, and the real service would make every case depend on a live probe."""

    def web_tools_disabled(self) -> frozenset[str]:
        return frozenset()


async def _schema_chars(mode: str, permission: str) -> tuple[int, int]:
    """(tool count, schema characters) a real run in this mode and at this level would
    actually be handed — resolved through the composed toolset stack the engine hands the
    Agent, and through the same ``effective_disabled_tools`` every run path fills
    ``RunDeps.disabled_tools`` from. Re-deriving the withheld set here would measure a
    narrowing this file invented rather than the one the app performs, and would stay
    green if the real path stopped applying the level at all."""
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    disabled = await effective_disabled_tools(
        SettingsStore(engine), _AllOnline(), "operator", mode=mode, permission=permission
    )
    run = Run(id="t", kind="chat", owner_id="operator", stream=RunStream())
    deps = RunDeps(
        run=run,
        owner_id="operator",
        disabled_tools=disabled,
        mode=mode,
        permission=permission,
    )
    ctx = RunContext(deps=deps, model=TestModel(), usage=RunUsage())
    tools = await build_agent_toolsets(full_tool_categories())[0].get_tools(ctx)
    overhead = measure_overhead(None, [], [tool.tool_def for tool in tools.values()])
    return len(tools), overhead.tools


async def test_the_whole_catalog_stays_inside_its_ceiling():
    count, chars = await _schema_chars("normal", "auto")
    assert count > 0
    assert chars < CATALOG_CEILING_CHARS, (
        f"the tool catalog now costs {chars} characters "
        f"(~{int(chars / CHARS_PER_TOKEN_JSON)} tokens) at the head of every request — "
        "either take something out, or raise the ceiling on purpose"
    )


async def test_plan_hands_the_model_a_fraction_of_the_catalog():
    for mode in MODES:
        _, acting = await _schema_chars(mode, "auto")
        _, planning = await _schema_chars(mode, "plan")
        assert planning < acting * 0.6, (
            f"{mode} at plan level costs {planning} characters against {acting} acting — "
            "the read-only narrowing has stopped narrowing"
        )


async def test_only_plan_narrows_the_catalog():
    # The other three levels decide *at the call*: taking a tool out of their catalog
    # would tell the model the capability does not exist rather than that it needs
    # permission, so their cost is identical by design.
    acting = {
        level: await _schema_chars("normal", level)
        for level in PERMISSION_LEVELS
        if level != "plan"
    }
    assert len(set(acting.values())) == 1, acting
