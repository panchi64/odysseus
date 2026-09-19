"""Slash commands — names the operator types to reach what the platform already has.

Small pieces and no machinery, the same shape ``services/subagents`` keeps:

- ``spec.py`` — what a command *is*, as data; the locality rule that ranks two of them
  sharing a name; and the invocation that gets written onto a turn.
- ``actions.py`` — the thread actions this installation ships, each naming an id the
  client maps onto a relay it already owns.
- ``registry.py`` — which commands a given request may offer, and what a typed name means.
- ``expand.py`` — the tail block an invoked command contributes to that turn.
- ``authoring.py`` — what makes a written command well-formed, shared by both things that
  write one.
- ``store.py`` — the operator's own saved workflows, the one source this package owns.
- ``definitions.py`` — the commands a project declares in its own files.

**Five sources, one shape.** What the installation ships (actions, the sub-agent roster),
what the operator wrote (published skills, saved workflows), and what the project declared
(``commands/*.md``, ``agents/*.md``). Only ``store.py`` is a table this feature owns; the
rest are things that already existed, given a name that can be typed.

What is deliberately absent is an executor. A command resolves to a skill, a sub-agent, a
template or an id; nothing here opens, launches, navigates or writes.

And nothing here is shown to the **model**. There is no toolset and no instruction
provider: a command is something the *operator* reaches for, and the tail block one
produces is the only trace of it the model ever sees.
"""

from __future__ import annotations

from services.commands.actions import BUILTIN_ACTIONS, NEEDS_CONVERSATION
from services.commands.expand import expand
from services.commands.registry import GROUPS, CatalogEntry, CommandRegistry
from services.commands.spec import (
    ActionId,
    CommandKind,
    CommandSource,
    CommandSpec,
    Invocation,
)

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
    "Invocation",
    "expand",
]
