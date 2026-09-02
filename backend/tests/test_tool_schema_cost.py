"""What the tool catalog costs before the model has read a single message.

Every tool the model is offered arrives as name + description + JSON schema, at the head
of every request, whether or not the turn goes anywhere near it. That is the one part of
the window nobody chose and nobody sees, so it is measured here — against the *real*
assembled catalog (core plus every manifest's export), through the same
``agent.overhead`` sizing the context gauge draws from, so the unit here and the unit the
operator reads stay one unit.

Since the dormant categories landed there are two numbers, not one. A **fresh request**
carries ~23k characters across 31 tools — call it ~5.6k tokens — because five categories
(``browse``, ``calendar``, ``mail``, ``research``, ``vault``) ship with their schemas
withheld until the model asks for the group. The **corpus** behind it, every dormant group
revealed, is ~43k across 65; ``browse`` alone is 18 tools and ~15k of that, which is why it
is dormant. A Plan-level turn is handed ~21k of the corpus, because everything above
``read`` is withheld outright rather than offered and refused.

Three things are pinned. A **ceiling on the fresh request**, which is what a turn actually
pays. A looser **ceiling on the corpus**, because a tool added to a dormant group is
invisible to the first ceiling and still costs the turn that opens the group. And the
**narrowing**, so the withholding that makes Plan cheap stays real: it is enforcement first
and a saving second, and a regression would be invisible from either side alone. A failure
here is not necessarily a bug, but it is always a decision somebody should make
deliberately.
"""

from __future__ import annotations

from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from agent.overhead import measure_overhead
from core.db import init_db, make_engine
from core.text import CHARS_PER_TOKEN_JSON
from harness.discovery import discover_manifests
from runs import Run, RunStream
from services.modes import MODES
from services.permissions import PERMISSION_LEVELS
from services.settings_store import SettingsStore
from services.tool_policy import effective_disabled_tools
from tools import RunDeps, build_agent_toolsets

from ._helpers import full_tool_categories

#: What a fresh request's catalog may cost, in characters of serialized schema. Set a
#: little above today's ~23k so an ordinary addition lands quietly and a category-sized one
#: does not. Characters rather than tokens for the same reason the measurement itself uses
#: them: no tokenizer, no provider, no drift.
CATALOG_CEILING_CHARS = 26_000

#: The same for the whole corpus — every dormant group revealed. Deferral moves a group's
#: cost from every turn to the turns that want it; it does not make the group free, and a
#: ceiling that only watched the fresh request would let the dormant half grow unwatched.
CORPUS_CEILING_CHARS = 50_000


class _AllOnline:
    """Offline mode with nothing suspended — this file measures the catalog, not
    connectivity, and the real service would make every case depend on a live probe."""

    def web_tools_disabled(self) -> frozenset[str]:
        return frozenset()


def _dormant_categories() -> tuple[str, ...]:
    """The dormant declarations a real app assembles, read off the manifests the same way
    ``full_tool_categories`` reads their toolsets. Restating the set here would measure a
    deferral this file invented rather than the one the app performs."""
    return tuple(entry.category for manifest in discover_manifests() for entry in manifest.dormant)


async def _catalog(mode: str, permission: str) -> tuple[tuple[int, int], tuple[int, int]]:
    """``((tools, chars) on a fresh request, (tools, chars) with every group revealed)`` for
    a real run in this mode and at this level — resolved through the composed toolset stack
    the engine hands the Agent, and through the same ``effective_disabled_tools`` every run
    path fills ``RunDeps.disabled_tools`` from. Re-deriving the withheld set here would
    measure a narrowing this file invented rather than the one the app performs, and would
    stay green if the real path stopped applying the level at all.

    A dormant tool stays in the resolved toolset carrying ``defer_loading`` — that flag is
    what the model layer reads to keep the schema off the wire — so the fresh figure is the
    same subtraction the request performs, not a second opinion about it."""
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
    stack = build_agent_toolsets(full_tool_categories(), dormant=_dormant_categories())[0]
    tools = await stack.get_tools(ctx)
    corpus = [tool.tool_def for tool in tools.values()]
    fresh = [tool_def for tool_def in corpus if not tool_def.defer_loading]
    return (
        (len(fresh), measure_overhead(None, [], fresh).tools),
        (len(corpus), measure_overhead(None, [], corpus).tools),
    )


async def _corpus_chars(mode: str, permission: str) -> int:
    _, (_, chars) = await _catalog(mode, permission)
    return chars


async def test_a_fresh_request_stays_inside_its_ceiling():
    (count, chars), _ = await _catalog("normal", "auto")
    assert count > 0
    assert chars < CATALOG_CEILING_CHARS, (
        f"a fresh request's tool catalog now costs {chars} characters "
        f"(~{int(chars / CHARS_PER_TOKEN_JSON)} tokens) at the head of every request — "
        "either take something out, make its category dormant, or raise the ceiling on purpose"
    )


async def test_the_whole_corpus_stays_inside_its_ceiling():
    _, (count, chars) = await _catalog("normal", "auto")
    assert count > 0
    assert chars < CORPUS_CEILING_CHARS, (
        f"the tool corpus now costs {chars} characters "
        f"(~{int(chars / CHARS_PER_TOKEN_JSON)} tokens) once every dormant group is open — "
        "either take something out, or raise the ceiling on purpose"
    )


async def test_the_dormant_groups_are_most_of_what_a_turn_no_longer_pays():
    """The saving is the whole reason the groups are dormant, so it is pinned rather than
    left to be re-derived from two ceilings that move independently."""
    fresh, corpus = await _catalog("normal", "auto")
    assert fresh[1] < corpus[1] * 0.6, (
        f"a fresh request carries {fresh[1]} characters of the corpus' {corpus[1]} — "
        "deferral has stopped deferring most of what it used to"
    )


async def test_plan_hands_the_model_a_fraction_of_the_catalog():
    # Measured over the corpus: the narrowing is the permission level withholding tools
    # outright, and reading it off the fresh request would net it against deferral, which
    # withholds for an unrelated reason and hands everything back on request.
    for mode in MODES:
        acting = await _corpus_chars(mode, "auto")
        planning = await _corpus_chars(mode, "plan")
        assert planning < acting * 0.6, (
            f"{mode} at plan level costs {planning} characters against {acting} acting — "
            "the read-only narrowing has stopped narrowing"
        )


async def test_only_plan_narrows_the_catalog():
    # The other three levels decide *at the call*: taking a tool out of their catalog
    # would tell the model the capability does not exist rather than that it needs
    # permission, so their cost is identical by design — before and after deferral, which
    # is decided per category and knows nothing about the level.
    acting = {
        level: await _catalog("normal", level)
        for level in PERMISSION_LEVELS
        if level != "plan"
    }
    assert len(set(acting.values())) == 1, acting
