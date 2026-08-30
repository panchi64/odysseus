"""The operator's tool-enablement policy (`AE-3.3`).

The enforcement point already exists: ``tools/toolsets.py``'s enabled gate drops a
disabled tool from the catalog the model is offered, so the agent can neither see nor
invoke it. This module is the **operator's half** — which tools they turned off, made
durable, and composed with the suspensions the system decides on its own.

Four independent sources feed one set:

- **the operator's explicit choices**, persisted through ``settings_store`` under
  ``tools.disabled`` as a plain JSON list of namespaced tool names. Policy, not content,
  so it stays in the clear like every other app preference;
- **offline mode's automatic web-tool suspension** (``services/offline``), derived from
  connectivity rather than chosen;
- **the run's mode** — whether a tool belongs in a chat thread or a coding one;
- **the model's own reach** — a tool that answers with an image is withheld from a model
  that cannot see one.

They **union**: :func:`effective_disabled_tools` is the one place that rule lives, so no
run path can apply one source and silently drop the others. Every site that fills
``RunDeps.disabled_tools`` calls it — the live chat turn, the approval-resume path, and
the scheduler's unattended task executor.

**Mode is a filter, not a second catalog.** ``app.state.tool_categories`` is assembled
once at startup and ``tools/catalog.py`` derives the operator's settings list from it;
building a different mapping per mode would let the settings page and the agent's real
stack disagree, which is the exact failure the namespacing was built to prevent. So the
`shell` and `repo` categories are registered like every other, listed like every other,
and simply withheld from a run that is not in their mode.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING

from services.settings_store import DISABLED_TOOLS_KEY, SettingsStore

if TYPE_CHECKING:
    from services.offline import OfflineModeService

logger = logging.getLogger(__name__)


def _decode(raw: str | None) -> frozenset[str]:
    """The stored JSON list as a name set. A missing, malformed, or wrongly-shaped value
    reads as "nothing disabled" rather than raising — a corrupted preference must never
    take the whole tool catalog away from the agent (the same fail-open-to-the-default
    posture ``settings_store``'s own coercers take)."""
    if not raw:
        return frozenset()
    try:
        names = json.loads(raw)
    except ValueError:
        logger.warning("tool policy: ignoring unparseable %s value", DISABLED_TOOLS_KEY)
        return frozenset()
    if not isinstance(names, list):
        logger.warning("tool policy: ignoring non-list %s value", DISABLED_TOOLS_KEY)
        return frozenset()
    return frozenset(n for n in names if isinstance(n, str) and n)


async def get_disabled_tools(settings: SettingsStore, owner_id: str) -> frozenset[str]:
    """The tools the operator has explicitly turned off, by namespaced name."""
    return _decode(await settings.get(owner_id, DISABLED_TOOLS_KEY))


async def set_tool_enabled(
    settings: SettingsStore, owner_id: str, name: str, enabled: bool
) -> frozenset[str]:
    """Flip one tool on or off; returns the operator's full disabled set afterwards.

    Read-modify-write on a single-operator store — two flips racing each other is not a
    case that arises, and the surface that drives this is one operator's settings screen.
    The name is validated against the live catalog by the route, so an unknown name never
    reaches here to rot in the stored set.
    """
    current = await get_disabled_tools(settings, owner_id)
    updated = current - {name} if enabled else current | {name}
    if updated != current:
        await _store(settings, owner_id, updated)
    return updated


async def _store(settings: SettingsStore, owner_id: str, names: Iterable[str]) -> None:
    """Persist the set, sorted so the stored value is stable across equal sets."""
    await settings.set(owner_id, DISABLED_TOOLS_KEY, json.dumps(sorted(names)))


# The tools that belong to one mode and not the other, by namespaced name. Written out
# rather than derived from the category mapping because `tools/` sits *above* this layer
# and importing the catalog here would invert the dependency order. The literal set is
# checked against the real catalog by `tests/test_mode_tools.py`, so a renamed or dropped
# tool fails there rather than silently ceasing to be filtered.
CODING_ONLY_TOOLS = frozenset(
    {
        "shell_run_command",
        "shell_start_command",
        "shell_check_command",
        "shell_stop_command",
        "repo_inventory_agent_context",
    }
)

# Coding mode has exactly one way to run something — the shell, in the worktree the file
# tools are rooted at. Leaving `code_execute` alongside it would offer the model a second
# filesystem it could edit in and never ship from, which is the failure the one-workspace
# rule exists to prevent; `code_run_host_command` goes with it because its own sandboxed
# fence is a different (and, in a worktree, redundant) boundary.
CHAT_ONLY_TOOLS = frozenset({"code_execute", "code_run_host_command"})


# Tools whose *result* only a vision model can read — they return image content rather
# than text. Written out here for the same reason the mode sets are: `services/` sits
# below `tools/`, so importing the category that owns them would invert the dependency
# order. `tests/test_tool_policy.py` checks the literal against the real catalog.
VISION_ONLY_TOOLS = frozenset({"browse_screenshot"})


def vision_disabled_tools(vision: bool) -> frozenset[str]:
    """The tools a model that cannot see should not be offered.

    Not a safety gate — a courtesy and a cost one. A text-only model handed a screenshot
    tool spends a call producing image content its provider will reject or silently drop,
    and learns nothing either way. It loses nothing by the withholding: reading a page
    through `snapshot`/`get_text` is the cheaper path the browser capability recommends
    first regardless, and the operator still watches the live page in the panel.
    """
    return frozenset() if vision else VISION_ONLY_TOOLS


def mode_disabled_tools(mode: str) -> frozenset[str]:
    """The tools that do not belong in ``mode``.

    An unrecognised mode is treated as chat — the conservative answer, since chat mode is
    the one that never reaches the host.
    """
    return CHAT_ONLY_TOOLS if mode == "coding" else CODING_ONLY_TOOLS


async def effective_disabled_tools(
    settings: SettingsStore,
    offline: OfflineModeService,
    owner_id: str,
    *,
    mode: str = "chat",
    vision: bool = True,
) -> frozenset[str]:
    """Everything hidden from the agent this run: the operator's set **unioned** with
    offline mode's automatic web suspension, the tools that don't belong in ``mode``, and
    the ones whose results this run's model cannot read.

    A union, never a replacement — the four answer different questions ("the operator does
    not want this tool", "this tool cannot work right now", "this tool is not part of this
    kind of thread", "this model cannot read what this tool returns"), and any one of them
    alone is enough to withhold a tool.

    ``vision`` defaults to True — permissive — because the callers that cannot know
    (a background agent that resolves its own model) should not have tools taken away by
    an assumption; the interactive paths, which do know, pass the resolved answer.
    """
    return (
        await get_disabled_tools(settings, owner_id)
        | offline.web_tools_disabled()
        | mode_disabled_tools(mode)
        | vision_disabled_tools(vision)
    )
