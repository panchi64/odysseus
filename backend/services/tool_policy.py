"""The operator's tool-enablement policy (`AE-3.3`).

The enforcement point already exists: ``tools/toolsets.py``'s enabled gate drops a
disabled tool from the catalog the model is offered, so the agent can neither see nor
invoke it. This module is the **operator's half** — which tools they turned off, made
durable, and composed with the suspensions the system decides on its own.

Five independent sources feed one set:

- **the operator's explicit choices**, persisted through ``settings_store`` under
  ``tools.disabled`` as a plain JSON list of namespaced tool names. Policy, not content,
  so it stays in the clear like every other app preference;
- **offline mode's automatic web-tool suspension** (``services/offline``), derived from
  connectivity rather than chosen;
- **the run's mode** — whether a tool belongs in this kind of thread, read off the mode
  registry (``services/modes.py``) rather than restated here;
- **the run's permission level** — under Plan, every tool that would change something is
  withheld outright, classified by ``services/tool_sensitivity.py``;
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
and simply withheld from a run that is not in their mode. **Which** categories a mode
admits is the registry's answer, not this module's — mode is one axis of a thread, and
this module only knows how to turn an axis into a withheld set.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING

from services.modes import (
    DEFAULT_MODE,
    DEFAULT_PERMISSION,
    MODE_SCOPED_TOOLS,
    mode_spec,
    permission_level,
)
from services.settings_store import DISABLED_TOOLS_KEY, SettingsStore
from services.tool_sensitivity import Sensitivity, tools_above

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
    """The tools that do not belong in ``mode`` — every mode-scoped category the mode's
    spec does not admit, flattened to namespaced names.

    Derived from the registry rather than written out per mode, so a fourth mode withholds
    the right tools the moment its row exists. An unrecognised mode resolves to Normal
    (``services/modes.py``), which is the conservative direction: Normal is the mode that
    never reaches the host, so a corrupt stored value cannot open the shell up.
    """
    admitted = mode_spec(mode).categories
    return frozenset(
        name
        for category, names in MODE_SCOPED_TOOLS.items()
        if category not in admitted
        for name in names
    )


# The Planning toolset's writes — the one mutation a Plan turn exists to make, and so the
# one exemption from Plan's withholding. A read-only thread that could not record what it
# decided would have no way to end. Written out here for the same reason
# `VISION_ONLY_TOOLS` is, and pinned against the live catalog by
# `tests/test_tool_sensitivity.py`. Reading the plan is already admitted — it classifies
# as `read` — so only the writes are listed.
PLANNING_TOOLS = frozenset(
    {
        "plan_add_task",
        "plan_remove_task",
        "plan_update_task_status",
        "plan_update_task_statuses",
        "plan_write_plan",
    }
)


def permission_disabled_tools(level: str) -> frozenset[str]:
    """The tools a run at ``level`` must not even be offered.

    Only **Plan** narrows the catalog, and it is the reason the sensitivity classes exist:
    a read-only turn is the one case where withholding beats asking. The other three levels
    decide *at the call* — they let the model see a tool and then gate its execution — so
    they withhold nothing here; taking a tool out of their catalog would tell the model the
    capability does not exist rather than that it needs permission, and it would answer as
    if the operator had never had the option.

    Withholding rather than prompt-toggling is deliberate. A mode that only *asks* the
    model to stay read-only is enforcement by cooperation, which stops working precisely
    when it matters. A tool that is not in the catalog cannot be called by a model that
    decides otherwise.

    An unrecognised level lands on Plan (``services/modes.py``), so a corrupt stored value
    reads as "this thread may only look", not as free rein.
    """
    if permission_level(level) != "plan":
        return frozenset()
    return tools_above(Sensitivity.READ) - PLANNING_TOOLS


async def effective_disabled_tools(
    settings: SettingsStore,
    offline: OfflineModeService,
    owner_id: str,
    *,
    mode: str = DEFAULT_MODE,
    permission: str = DEFAULT_PERMISSION,
    vision: bool = True,
) -> frozenset[str]:
    """Everything hidden from the agent this run: the operator's set **unioned** with
    offline mode's automatic web suspension, the tools that don't belong in ``mode``, the
    ones this run's ``permission`` level does not let it act with, and the ones whose
    results this run's model cannot read.

    A union, never a replacement — the five answer different questions ("the operator does
    not want this tool", "this tool cannot work right now", "this tool is not part of this
    kind of thread", "this thread may not act at all", "this model cannot read what this
    tool returns"), and any one of them alone is enough to withhold a tool.

    ``permission`` defaults to the level that withholds nothing, so a caller with no level
    to pass is unaffected; ``vision`` defaults to True — permissive — because the callers
    that cannot know (a background agent that resolves its own model) should not have tools
    taken away by an assumption; the interactive paths, which do know, pass the resolved
    answer.
    """
    return (
        await get_disabled_tools(settings, owner_id)
        | offline.web_tools_disabled()
        | mode_disabled_tools(mode)
        | permission_disabled_tools(permission)
        | vision_disabled_tools(vision)
    )
