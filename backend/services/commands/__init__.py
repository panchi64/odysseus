"""Slash commands — names the operator types to reach what the platform already has.

Four small pieces and no machinery, the same shape ``services/subagents`` keeps:

- ``spec.py`` — what a command *is*, as data, plus the locality rule that ranks two of
  them sharing a name.
- ``actions.py`` — the thread actions this installation ships, each naming an id the
  client maps onto a relay it already owns.
- ``registry.py`` — which commands a given request may offer, and what a typed name means.
- ``expand.py`` — the tail block an invoked command contributes to that turn.

What is deliberately absent is an executor. A command resolves to a skill, a sub-agent, a
template or an id; nothing here opens, launches, navigates or writes.
"""

from __future__ import annotations

from services.commands.actions import BUILTIN_ACTIONS, NEEDS_CONVERSATION
from services.commands.expand import expand
from services.commands.registry import GROUPS, CatalogEntry, CommandRegistry
from services.commands.spec import ActionId, CommandKind, CommandSource, CommandSpec

__all__ = [
    "BUILTIN_ACTIONS",
    "GROUPS",
    "NEEDS_CONVERSATION",
    "ActionId",
    "CatalogEntry",
    "CommandKind",
    "CommandRegistry",
    "CommandSource",
    "CommandSpec",
    "expand",
]
