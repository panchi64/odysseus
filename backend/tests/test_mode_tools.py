"""Mode as a tool filter — the registry turned into a withheld set.

`tests/test_modes.py` pins the registry's literal names against the live catalog. This is
the other half: that `mode_disabled_tools` actually withholds what a mode's spec does not
admit, that a real run resolves the same answer through the composed toolset stack, and
that mode composes with the operator's own set and offline's rather than replacing either.
"""

from __future__ import annotations

from services.modes import MODE_SCOPED_TOOLS
from services.tool_policy import (
    effective_disabled_tools,
    mode_disabled_tools,
    set_tool_enabled,
)

from .test_tool_policy import _agent_visible, _store, _StubOffline

OWNER = "operator"

WORKTREE_TOOLS = MODE_SCOPED_TOOLS["shell"] | MODE_SCOPED_TOOLS["repo"]
SANDBOX_TOOLS = MODE_SCOPED_TOOLS["code"]


class TestTheFilter:
    def test_a_sandbox_mode_hides_the_worktree_tools(self):
        assert mode_disabled_tools("normal") == WORKTREE_TOOLS
        assert mode_disabled_tools("research") == WORKTREE_TOOLS

    def test_code_hides_the_sandbox_runner(self):
        assert mode_disabled_tools("code") == SANDBOX_TOOLS

    def test_an_unknown_mode_is_treated_as_normal(self):
        # The conservative direction: Normal is the mode that never reaches the host, so a
        # corrupt stored value must not open the shell up.
        assert mode_disabled_tools("nonsense") == WORKTREE_TOOLS
        # The pre-rename vocabulary included — `coding` is not a mode any more.
        assert mode_disabled_tools("coding") == WORKTREE_TOOLS

    async def test_the_agent_is_actually_offered_a_shell_only_in_code_mode(self):
        # Through the composed toolset stack a real run resolves, not a re-derivation of
        # the naming rule.
        normal = await _agent_visible(mode_disabled_tools("normal"))
        research = await _agent_visible(mode_disabled_tools("research"))
        code = await _agent_visible(mode_disabled_tools("code"))
        assert "shell_run_command" not in normal
        assert "shell_run_command" not in research
        assert "code_execute" in normal
        assert "shell_run_command" in code
        assert "code_execute" not in code
        # Everything else is unaffected by the mode.
        assert {"memory_recall"} <= normal & research & code


class TestTheUnion:
    async def test_mode_composes_with_the_operator_set_and_offline(self):
        store = _store()
        await set_tool_enabled(store, OWNER, "builtin_now", False)
        offline = _StubOffline(frozenset({"web_search"}))
        disabled = await effective_disabled_tools(store, offline, OWNER, mode="code")
        assert "builtin_now" in disabled  # the operator's
        assert "web_search" in disabled  # offline's
        assert "code_execute" in disabled  # the mode's
        # ...and the mode's own tools are not withheld from the mode they belong to.
        assert "shell_run_command" not in disabled

    async def test_the_default_mode_is_normal(self):
        store = _store()
        offline = _StubOffline(frozenset())
        assert await effective_disabled_tools(store, offline, OWNER) == WORKTREE_TOOLS
