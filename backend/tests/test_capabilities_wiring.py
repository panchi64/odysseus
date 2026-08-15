"""Regression guard: every ``Capabilities(...)`` construction site must pass **every**
capability field.

``Capabilities`` exists so that adding a capability is one field, not a new parameter on
every call site — but the fields all default to ``None``, so a site that forgets one still
type-checks, still imports, and still passes every test. It just silently hands the agent a
``None`` handle, and the tool degrades to "unavailable" at runtime.

That is not hypothetical. The approval-resume site in ``routes/runs.py`` was missed when the
sprint's reserved handles were added, and it is the worst possible one to miss: mail-send,
vault-read and untrusted external tools are precisely the approval-gated tools, so the
resume path is the *only* way they ever execute. The tool would have gone unavailable at the
exact moment the operator approved it. ``routes/runs.py`` already carried a comment warning
about this class of bug; the comment was not enough, so this test is.
"""

from __future__ import annotations

import ast
from dataclasses import fields
from pathlib import Path

import pytest

from tools.deps import Capabilities

# Every module that builds the capability set handed to an orchestrator.
_CONSTRUCTION_SITES = ("harness/manifests/tasks.py", "routes/chat.py", "routes/runs.py")


def _keywords_at_each_call(path: Path) -> list[set[str]]:
    """The keyword-argument names of every ``Capabilities(...)`` call in a module."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        {kw.arg for kw in node.keywords if kw.arg is not None}
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Capabilities"
    ]


@pytest.mark.parametrize("relpath", _CONSTRUCTION_SITES)
def test_construction_site_passes_every_capability(relpath: str) -> None:
    path = Path(__file__).resolve().parents[1] / relpath
    calls = _keywords_at_each_call(path)
    assert calls, f"{relpath} no longer constructs Capabilities — update _CONSTRUCTION_SITES"

    expected = {f.name for f in fields(Capabilities)}
    for passed in calls:
        missing = expected - passed
        assert not missing, (
            f"{relpath} builds Capabilities without {sorted(missing)}. Every field must be "
            "passed explicitly: the None defaults mean a forgotten handle fails silently at "
            "runtime instead of loudly here."
        )


# Capabilities the *engine* consumes directly and no tool ever sees: the conversation
# auto-approval grants it splits deferred calls against, and the notifier it fires when a
# run parks. Everything else is tool-facing and must reach `RunDeps`.
_ENGINE_ONLY = frozenset({"grants", "notifications"})


def test_every_capability_reaches_run_deps() -> None:
    """Whatever ``Capabilities`` carries, ``RunDeps`` must expose to the tools — otherwise a
    capability is wired all the way to the engine and then dropped one layer short, which is
    invisible until a tool reports itself unavailable at runtime."""
    from tools.deps import RunDeps

    tool_facing = {f.name for f in fields(Capabilities)} - _ENGINE_ONLY
    missing = tool_facing - {f.name for f in fields(RunDeps)}
    assert not missing, (
        f"RunDeps is missing {sorted(missing)} — a capability the engine is handed but no "
        "tool can reach. If it is deliberately engine-only, add it to _ENGINE_ONLY with a "
        "reason rather than widening this test."
    )
