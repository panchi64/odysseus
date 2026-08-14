"""The operator-facing tool catalog — every tool, named exactly as the agent sees it.

`AE-3.3` lets the operator disable individual tools, which means the settings surface has
to *list* them. That list is **derived from the same registry the agent runs against**
(:func:`tools.toolsets.default_categories`), never hand-maintained: a tool that lands in
a category appears here the day it lands, and one that is renamed or removed cannot leave
a stale row behind that disables nothing.

Names are namespaced the way :meth:`AbstractToolset.prefixed` namespaces them —
``f"{category}_{tool}"`` — because that is the name the enabled gate matches on and the
name the model is offered. ``tests/test_tool_policy.py`` pins that convention against the
tool definitions a real agent run resolves, so a change in the library's prefixing is a
failing test rather than a settings screen whose toggles quietly stop applying.

**Scope.** Every category today is a Pydantic AI ``FunctionToolset``, whose tools are
known statically. A future toolset that resolves its tools dynamically (an external MCP
server, `MCP-*`) has nothing to enumerate here and contributes no rows — such tools carry
their own operator-facing trust surface (`AE-3.6`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from pydantic_ai import AbstractToolset

from . import toolsets
from .deps import RunDeps


@dataclass(frozen=True)
class ToolInfo:
    """One tool as the operator sees it on the settings surface."""

    # The namespaced name — what the enabled gate matches and what the model is offered.
    name: str
    # The category it was registered under, so the surface can group by cluster.
    category: str
    # The tool's own description (its docstring) — what the model is told it does, which
    # is also the most honest thing to show the operator deciding whether to allow it.
    description: str


def _flatten(text: str) -> str:
    """A description is a docstring, so its hard wrapping is an artifact of the source
    file rather than meaning. Collapse it to flowing text and let the surface lay it out;
    the whole description is kept — the operator deciding whether to allow a tool deserves
    everything the model was told about it."""
    return " ".join(text.split())


def tool_catalog(
    categories: Mapping[str, AbstractToolset[RunDeps]] | None = None,
) -> list[ToolInfo]:
    """Every registered tool, category-then-name ordered for a stable listing.

    ``categories`` overrides the live registry for tests; production passes nothing and
    gets exactly what :func:`tools.toolsets.build_agent_toolsets` composes.
    """
    # Reached through the module, not a from-import, so the registry stays the single
    # live source: a test (or a future dynamic registration) that replaces
    # ``default_categories`` is reflected here exactly as it is in the agent's own stack.
    cats = dict(categories) if categories is not None else toolsets.default_categories()
    catalog = [
        ToolInfo(
            name=f"{category}_{tool_name}",
            category=category,
            description=_flatten(tool.description or ""),
        )
        # A non-function toolset exposes no static tool registry; it contributes nothing
        # rather than breaking the listing (see the module docstring).
        for category, toolset in cats.items()
        for tool_name, tool in sorted(getattr(toolset, "tools", {}).items())
    ]
    return sorted(catalog, key=lambda t: (t.category, t.name))
