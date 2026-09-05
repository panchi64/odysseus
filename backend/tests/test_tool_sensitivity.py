"""Tool sensitivity classes, and the read-only catalog they make possible.

`services/tool_sensitivity.py` names every tool as a literal string, because `tools/` sits
above `services/` and importing the catalog there would invert the dependency order — the
same constraint `services/modes.py` works under, and the same tripwire: the literal is
checked against the catalog a real run resolves, in both directions. The direction that
actually rots is the second one. A tool added without a class would keep running under a
level that was supposed to withhold it, and nothing else in the system would notice.

The rest is the narrowing itself: that Plan is the only level that takes tools out of the
catalog, that it takes out everything that would change something *except* the plan writes
a Plan turn exists to make, and that a real run resolves the same answer through the
composed toolset stack rather than through a re-derivation of the rule.
"""

from __future__ import annotations

from services.permissions import PERMISSION_LEVELS, PLANNING_TOOLS
from services.tool_policy import (
    effective_disabled_tools,
    mode_disabled_tools,
    permission_disabled_tools,
    set_tool_enabled,
)
from services.tool_sensitivity import (
    SENSITIVITY_CLASSES,
    UNCLASSIFIED,
    Sensitivity,
    sensitivity_of,
    tools_above,
)
from tools.catalog import tool_catalog

from ._helpers import full_tool_categories
from .test_tool_policy import _agent_visible, _store, _StubOffline

OWNER = "operator"


def _catalog_names() -> set[str]:
    return {t.name for t in tool_catalog(full_tool_categories())}


def _classified() -> set[str]:
    return {name for names in SENSITIVITY_CLASSES.values() for name in names}


class TestEveryToolIsClassified:
    def test_every_classified_name_is_a_real_tool(self):
        assert _classified() <= _catalog_names()

    def test_every_real_tool_is_classified(self):
        # The half that rots. A new tool with no class would be silently treated as an
        # external effect — which is safe, but it would also be *wrong* for the reads,
        # withheld from a Plan turn that should have had it.
        assert _catalog_names() <= _classified()

    def test_no_tool_is_in_two_classes(self):
        total = sum(len(names) for names in SENSITIVITY_CLASSES.values())
        assert total == len(_classified())

    def test_every_class_is_used(self):
        # A class nothing carries is a distinction the system does not actually make.
        assert all(names for names in SENSITIVITY_CLASSES.values())
        assert set(SENSITIVITY_CLASSES) == set(Sensitivity)


class TestTheClassesAgreeWithTheExistingMarkings:
    def test_an_approval_marked_tool_is_never_a_read(self):
        # The classes were seeded from the markings, and the two must not drift apart: a
        # tool the operator is asked about before it runs is by definition not one that
        # merely observes.
        categories = full_tool_categories()
        for info in tool_catalog(categories):
            toolset = categories[info.category]
            name = info.name.removeprefix(f"{info.category}_")
            tool = getattr(toolset, "tools", {}).get(name)
            if getattr(tool, "requires_approval", False):
                assert sensitivity_of(info.name).above(Sensitivity.READ), info.name

    def test_the_tools_a_mode_withholds_are_all_effects(self):
        # `shell`, `repo` and `code` are scoped by mode because of what they reach; the
        # one read among them (`shell_check_command`) is scoped by the category it lives
        # in, not by its own class.
        assert sensitivity_of("shell_run_command") is Sensitivity.HOST_EXEC
        assert sensitivity_of("code_execute") is Sensitivity.HOST_EXEC
        assert sensitivity_of("repo_inventory_agent_context") is Sensitivity.READ


class TestResolvingAName:
    def test_a_known_name_resolves_to_its_class(self):
        assert sensitivity_of("web_search") is Sensitivity.READ
        assert sensitivity_of("files_write_file") is Sensitivity.WORKSPACE_WRITE
        assert sensitivity_of("mail_send") is Sensitivity.EXTERNAL_EFFECT
        assert sensitivity_of("vault_get_entry") is Sensitivity.SECRET

    def test_an_operators_external_tool_is_treated_as_an_external_effect(self):
        # `external_{slug}_{tool}` names come from the operator's own MCP servers and
        # connectors, so no literal here can enumerate them. Unknown means unbounded.
        assert sensitivity_of("external_acme_deploy") is UNCLASSIFIED
        assert UNCLASSIFIED is Sensitivity.EXTERNAL_EFFECT

    def test_reading_a_page_is_still_reading(self):
        # Network reach is not the axis. A fetch leaves nothing different behind it; a
        # click on the same page, in the same browser session, can.
        assert sensitivity_of("web_fetch") is Sensitivity.READ
        assert sensitivity_of("browse_snapshot") is Sensitivity.READ
        assert sensitivity_of("browse_click") is Sensitivity.EXTERNAL_EFFECT


class TestEscalation:
    def test_a_read_escalates_past_nothing(self):
        assert not Sensitivity.READ.above(Sensitivity.READ)
        assert Sensitivity.WORKSPACE_WRITE.above(Sensitivity.READ)
        assert Sensitivity.SECRET.above(Sensitivity.WORKSPACE_WRITE)

    def test_the_three_effect_classes_are_not_ordered_among_themselves(self):
        # They are kinds of reach, not degrees of one. A policy that wants to treat a
        # shell command differently from a sent email has to name them.
        for one in (Sensitivity.HOST_EXEC, Sensitivity.EXTERNAL_EFFECT, Sensitivity.SECRET):
            for other in (
                Sensitivity.HOST_EXEC,
                Sensitivity.EXTERNAL_EFFECT,
                Sensitivity.SECRET,
            ):
                assert not one.above(other)

    def test_tools_above_read_is_everything_that_changes_something(self):
        above = tools_above(Sensitivity.READ)
        assert _classified() - above == SENSITIVITY_CLASSES[Sensitivity.READ]
        assert "files_read_file" not in above
        assert "files_write_file" in above


class TestPlanNarrowsTheCatalog:
    def test_only_plan_withholds_anything(self):
        for level in PERMISSION_LEVELS - {"plan"}:
            assert permission_disabled_tools(level) == frozenset()
        assert permission_disabled_tools("plan")

    def test_an_unknown_level_is_read_only(self):
        # Fail closed: a corrupt stored value leaves the model able to look and to plan.
        assert permission_disabled_tools("nonsense") == permission_disabled_tools("plan")
        assert permission_disabled_tools("") == permission_disabled_tools("plan")

    def test_plan_keeps_every_read(self):
        withheld = permission_disabled_tools("plan")
        assert not withheld & SENSITIVITY_CLASSES[Sensitivity.READ]

    def test_plan_keeps_the_plan_writes_it_ends_with(self):
        # The one exemption. A read-only turn that could not record what it decided would
        # have no way to end.
        withheld = permission_disabled_tools("plan")
        assert not withheld & PLANNING_TOOLS
        assert "plan_read_plan" not in withheld

    def test_the_exemption_is_not_a_no_op(self):
        # The set names the whole task list, and its writes are what the rank rule would
        # otherwise have taken away — the read in it is exempt anyway and is listed so the
        # exemption reads as one surface rather than half of one.
        assert PLANNING_TOOLS <= _catalog_names()
        writes = {n for n in PLANNING_TOOLS if sensitivity_of(n) is not Sensitivity.READ}
        assert writes
        for name in writes:
            assert sensitivity_of(name) is Sensitivity.WORKSPACE_WRITE

    def test_plan_withholds_every_other_effect(self):
        withheld = permission_disabled_tools("plan")
        assert {
            "code_execute",
            "files_write_file",
            "mail_send",
            "memory_remember",
            "shell_run_command",
            "vault_get_entry",
        } <= withheld


class TestWhatAPlanTurnActuallySees:
    async def test_the_agent_is_offered_reads_and_the_plan_and_nothing_else(self):
        # Through the composed toolset stack a real run resolves, not a re-derivation of
        # the rule: a withheld tool is one the model can neither see nor invoke.
        visible = await _agent_visible(permission_disabled_tools("plan"))
        assert {"files_read_file", "web_search", "corpus_retrieve"} <= visible
        assert {"plan_write_plan", "plan_read_plan"} <= visible
        assert not {"files_write_file", "code_execute", "mail_send"} & visible

    async def test_a_plan_turn_carries_fewer_schemas_than_a_full_one(self):
        # The cost half of the argument: the tools a Plan turn cannot use are schemas it
        # does not pay for either. Every tool it loses is one that would change something.
        full = await _agent_visible(frozenset())
        planning = await _agent_visible(permission_disabled_tools("plan"))
        assert planning < full
        assert full - planning == permission_disabled_tools("plan") & full


class TestTheUnion:
    async def test_the_level_composes_with_the_other_sources(self):
        store = _store()
        await set_tool_enabled(store, OWNER, "builtin_now", False)
        offline = _StubOffline(frozenset({"web_search"}))
        disabled = await effective_disabled_tools(
            store, offline, OWNER, mode="code", permission="plan"
        )
        assert "builtin_now" in disabled  # the operator's
        assert "web_search" in disabled  # offline's
        assert "code_execute" in disabled  # the mode's
        assert "files_write_file" in disabled  # the level's
        # ...and the level does not take back what nothing withheld.
        assert "files_read_file" not in disabled

    async def test_a_caller_with_no_level_is_unaffected(self):
        store = _store()
        offline = _StubOffline(frozenset())
        assert await effective_disabled_tools(store, offline, OWNER) == mode_disabled_tools(
            "normal"
        )
