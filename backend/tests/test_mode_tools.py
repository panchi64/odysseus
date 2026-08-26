"""Mode as a tool filter, and the tripwire under it.

`services/tool_policy.py` names the mode-scoped tools as literal strings, because `tools/`
sits above `services/` and importing the catalog there would invert the dependency order.
A literal set rots silently: rename `shell_run_command` and the filter simply stops
matching, which reads as "coding tools now available in chat" — the exact failure the
`shell` guard exists to prevent. So the names are checked against the real catalog here.

The rest is the union rule: mode composes with the operator's own set and offline's, and
never replaces either.
"""

from __future__ import annotations

from services.tool_policy import (
    CHAT_ONLY_TOOLS,
    CODING_ONLY_TOOLS,
    effective_disabled_tools,
    mode_disabled_tools,
    set_tool_enabled,
)
from tools.catalog import tool_catalog

from ._helpers import full_tool_categories
from .test_tool_policy import _agent_visible, _store, _StubOffline

OWNER = "operator"


def _catalog_names() -> set[str]:
    return {t.name for t in tool_catalog(full_tool_categories())}


class TestTheNamesAreReal:
    def test_every_mode_scoped_name_exists_in_the_catalog(self):
        names = _catalog_names()
        assert CODING_ONLY_TOOLS <= names
        assert CHAT_ONLY_TOOLS <= names

    def test_the_two_sets_are_disjoint(self):
        # A tool in both would be hidden in every mode — visible in the settings screen
        # and reachable from nowhere.
        assert not (CODING_ONLY_TOOLS & CHAT_ONLY_TOOLS)

    def test_every_shell_and_repo_tool_is_coding_only(self):
        # The set is written out by hand, so a *new* shell tool would otherwise be
        # silently reachable from a chat thread.
        scoped = {n for n in _catalog_names() if n.startswith(("shell_", "repo_"))}
        assert scoped == CODING_ONLY_TOOLS


class TestTheFilter:
    def test_chat_hides_the_coding_tools(self):
        assert mode_disabled_tools("chat") == CODING_ONLY_TOOLS

    def test_coding_hides_the_sandbox_runner(self):
        assert mode_disabled_tools("coding") == CHAT_ONLY_TOOLS

    def test_an_unknown_mode_is_treated_as_chat(self):
        # The conservative direction: chat mode is the one that never reaches the host,
        # so a corrupt stored value must not open the shell up.
        assert mode_disabled_tools("nonsense") == CODING_ONLY_TOOLS

    async def test_the_agent_is_actually_offered_a_shell_only_in_coding_mode(self):
        # Through the composed toolset stack a real run resolves, not a re-derivation of
        # the naming rule.
        chat = await _agent_visible(mode_disabled_tools("chat"))
        coding = await _agent_visible(mode_disabled_tools("coding"))
        assert "shell_run_command" not in chat
        assert "code_execute" in chat
        assert "shell_run_command" in coding
        assert "code_execute" not in coding
        # Everything else is unaffected by the mode.
        assert "memory_recall" in chat and "memory_recall" in coding


class TestTheUnion:
    async def test_mode_composes_with_the_operator_set_and_offline(self):
        store = _store()
        await set_tool_enabled(store, OWNER, "builtin_now", False)
        offline = _StubOffline(frozenset({"web_search"}))
        disabled = await effective_disabled_tools(store, offline, OWNER, mode="coding")
        assert "builtin_now" in disabled  # the operator's
        assert "web_search" in disabled  # offline's
        assert "code_execute" in disabled  # the mode's
        # ...and the mode's own tools are not withheld from the mode they belong to.
        assert "shell_run_command" not in disabled

    async def test_the_default_mode_is_chat(self):
        store = _store()
        offline = _StubOffline(frozenset())
        assert await effective_disabled_tools(store, offline, OWNER) == CODING_ONLY_TOOLS
