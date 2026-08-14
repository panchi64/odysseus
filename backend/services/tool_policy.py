"""The operator's tool-enablement policy (`AE-3.3`).

The enforcement point already exists: ``tools/toolsets.py``'s enabled gate drops a
disabled tool from the catalog the model is offered, so the agent can neither see nor
invoke it. This module is the **operator's half** — which tools they turned off, made
durable, and composed with the suspensions the system decides on its own.

Two independent sources feed one set:

- **the operator's explicit choices**, persisted through ``settings_store`` under
  ``tools.disabled`` as a plain JSON list of namespaced tool names. Policy, not content,
  so it stays in the clear like every other app preference;
- **offline mode's automatic web-tool suspension** (``services/offline``), derived from
  connectivity rather than chosen.

They **union**: :func:`effective_disabled_tools` is the one place that rule lives, so no
run path can apply one source and silently drop the other. Every site that fills
``RunDeps.disabled_tools`` calls it — the live chat turn, the approval-resume path, and
the scheduler's unattended task executor.
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


async def effective_disabled_tools(
    settings: SettingsStore, offline: OfflineModeService, owner_id: str
) -> frozenset[str]:
    """Everything hidden from the agent this run: the operator's set **unioned** with
    offline mode's automatic web suspension.

    A union, never a replacement — the two answer different questions ("the operator does
    not want this tool" vs "this tool cannot work right now"), and either one alone is
    enough to withhold a tool.
    """
    return await get_disabled_tools(settings, owner_id) | offline.web_tools_disabled()
