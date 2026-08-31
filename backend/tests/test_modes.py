"""The mode registry, and the tripwire under its literal tool names.

`services/modes.py` names each mode-scoped category's tools as literal strings, because
`tools/` sits above `services/` and importing the catalog there would invert the dependency
order. A literal set rots silently: add a fifth shell tool and the filter simply stops
covering it, which reads as "a host shell is now reachable from a sandbox thread" — the
exact failure the mode filter exists to prevent. So the names are checked against the
catalog a real run resolves, in *both* directions: every listed name is real, and every
real name in those categories is listed.

The rest is the registry's own coherence — a spec's id agrees with its key, an unknown
stored value degrades to the mode that reaches the least, and the two workspace kinds are
the two `services/workspace.py` can actually build.
"""

from __future__ import annotations

from pydantic_ai.models.test import TestModel

from agent import build_chat_orchestrator, engine
from core.config import get_settings
from runs import RunRegistry
from services.conversations import ConversationBinding
from services.modes import DEFAULT_MODE, MODE_SCOPED_TOOLS, MODES, mode_spec
from tools.catalog import tool_catalog

from ._helpers import client_app, full_tool_categories, patch_model_resolution


def _catalog() -> list:
    return tool_catalog(full_tool_categories())


class TestTheNamesAreReal:
    def test_every_scoped_name_exists_in_the_catalog(self):
        names = {t.name for t in _catalog()}
        for category, scoped in MODE_SCOPED_TOOLS.items():
            assert scoped <= names, f"{category} names a tool the catalog does not have"

    def test_a_scoped_category_lists_every_tool_it_registers(self):
        # The direction that actually rots. A tool added to `shell` or `code` and not
        # added here would be offered in every mode, including the ones whose whole point
        # is that they cannot reach it.
        for category, scoped in MODE_SCOPED_TOOLS.items():
            registered = {t.name for t in _catalog() if t.category == category}
            assert registered == scoped, f"{category} has drifted from the registry"

    def test_a_scoped_category_is_a_real_category(self):
        categories = set(full_tool_categories())
        assert set(MODE_SCOPED_TOOLS) <= categories


class TestTheRegistryIsCoherent:
    def test_each_spec_agrees_with_its_key(self):
        for name, spec in MODES.items():
            assert spec.id == name

    def test_every_admitted_category_is_one_that_is_actually_contested(self):
        # Admitting a category nothing withholds is a no-op that reads like a decision.
        for spec in MODES.values():
            assert spec.categories <= set(MODE_SCOPED_TOOLS)

    def test_every_scoped_category_is_admitted_by_someone(self):
        # A category no mode admits is registered, listed in the operator's settings, and
        # reachable from nowhere.
        admitted = set().union(*(spec.categories for spec in MODES.values()))
        assert admitted == set(MODE_SCOPED_TOOLS)

    def test_only_code_works_on_the_operators_files(self):
        assert {name for name, s in MODES.items() if s.workspace == "worktree"} == {"code"}

    def test_the_default_mode_is_a_real_one(self):
        assert DEFAULT_MODE in MODES


class TestResolvingAStoredValue:
    def test_a_known_value_resolves_to_itself(self):
        assert mode_spec("code").id == "code"
        assert mode_spec("research").id == "research"

    def test_an_unknown_value_degrades_to_the_default(self):
        # A restored backup, a hand-edited row, or a thread written by a future build.
        # Normal is the conservative answer: it never reaches the host.
        assert mode_spec("nonsense").id == DEFAULT_MODE
        assert mode_spec("").workspace == "sandbox"
        # ...including the pre-rename vocabulary, which no longer means anything.
        assert mode_spec("coding").workspace == "sandbox"


class TestWhatEachModeCarries:
    def test_research_is_the_only_mode_with_prose_of_its_own(self):
        # The base prompt was written for Normal, and Code's difference announces itself
        # through its worktree and its tools — see `prompts/modes.py`.
        assert {name for name, s in MODES.items() if s.instructions} == {"research"}

    def test_research_raises_the_round_trip_floor(self):
        assert MODES["research"].request_limit is not None
        assert MODES["normal"].request_limit is None
        assert MODES["code"].request_limit is None


class TestTheRoundTripCeiling:
    """A mode's floor is a floor under the number *nobody chose*, and nothing more.

    The floor exists because a mode whose work genuinely cannot fit inside the shipped
    default would otherwise stop at a bound nothing about this deployment picked. That
    argument does not reach a number the operator typed: an operator who lowered the
    ceiling to 10 must not find a research turn taking sixty round trips while the
    settings page still reads 10.
    """

    async def _ceiling(self, monkeypatch, *, mode: str, request_limit: int | None) -> int:
        seen: list[int] = []
        real = engine.UsageLimits

        def record(**kwargs):
            seen.append(kwargs["request_limit"])
            return real(**kwargs)

        monkeypatch.setattr(engine, "UsageLimits", record)
        registry = RunRegistry()
        run = registry.submit(
            kind="chat",
            owner_id="operator",
            orchestrator=build_chat_orchestrator(
                "hi",
                model=TestModel(custom_output_text="ok"),
                binding=ConversationBinding(mode=mode),
                request_limit=request_limit,
            ),
        )
        await run.wait()
        assert seen, "the turn never built its usage bounds"
        return seen[0]

    async def test_a_mode_floor_raises_the_bound_nobody_chose(self, monkeypatch):
        # No operator setting: the config default is what the deploy shipped, and research
        # says it cannot do its work inside it.
        ceiling = await self._ceiling(monkeypatch, mode="research", request_limit=None)
        assert ceiling == max(get_settings().agent_request_limit, MODES["research"].request_limit)

    async def test_a_mode_without_a_floor_leaves_the_default_alone(self, monkeypatch):
        ceiling = await self._ceiling(monkeypatch, mode="normal", request_limit=None)
        assert ceiling == get_settings().agent_request_limit

    async def test_an_operator_who_lowered_the_ceiling_is_not_overruled(self, monkeypatch):
        # The whole point: 10 means 10, in every mode.
        assert MODES["research"].request_limit > 10
        assert await self._ceiling(monkeypatch, mode="research", request_limit=10) == 10

    async def test_an_operator_ceiling_above_the_floor_is_honoured_too(self, monkeypatch):
        assert await self._ceiling(monkeypatch, mode="research", request_limit=90) == 90


# --- over HTTP: the vocabulary a thread is actually created with ----------------------


class TestTheStoredVocabulary:
    async def test_a_research_thread_is_created_and_stored_as_one(self, monkeypatch):
        async with client_app() as (client, app):
            patch_model_resolution(monkeypatch)
            created = await client.post("/chat", json={"prompt": "hi", "mode": "research"})
            assert created.status_code == 202, created.text
            binding = await app.state.conversations.binding(created.json()["conversation_id"])
            assert binding.mode == "research"

    async def test_a_thread_with_no_mode_is_normal(self, monkeypatch):
        async with client_app() as (client, app):
            patch_model_resolution(monkeypatch)
            created = await client.post("/chat", json={"prompt": "hi"})
            binding = await app.state.conversations.binding(created.json()["conversation_id"])
            assert binding.mode == DEFAULT_MODE

    async def test_the_retired_vocabulary_is_refused_at_the_edge(self):
        # Not translated. A client still sending the old words is out of date, and
        # accepting them would leave two spellings of one mode alive in the database.
        async with client_app() as (client, _app):
            for retired in ("chat", "coding"):
                resp = await client.post("/chat", json={"prompt": "hi", "mode": retired})
                assert resp.status_code == 422, retired
