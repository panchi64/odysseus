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

from services.external_tools import ExternalTools

from . import toolsets
from .deps import RunDeps

# Tools whose approval gate is **runtime-conditional**: they raise ``ApprovalRequired``
# from inside the call rather than carrying ``requires_approval=True``, so — unlike the
# statically marked ones below — the marking cannot be read off the tool definition.
#
# `tools/recall_gate.py` gates every global, relevance-ranked recall (`AE-3.8`);
# `tools/documents.py` gates an edit or a suggestion against a document from *another*
# conversation, because provenance rather than the operation decides (`DOC-3`). Both
# gates can fire on any call, so both names belong in the vocabulary.
#
# External tools are conditional too, but they are neither static nor enumerable here —
# see `approval_scopes`.
_CONDITIONALLY_GATED = frozenset(
    {
        "corpus_retrieve",
        "memory_recall",
        "conversations_search",
        "document_edit",
        "document_suggest",
    }
)


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


async def approval_scopes(
    external: ExternalTools | None,
    owner_id: str,
    categories: Mapping[str, AbstractToolset[RunDeps]] | None = None,
) -> list[ToolInfo]:
    """Every tool that can pause a run for approval — the vocabulary a conversation grant
    (`AE-3.7`) or a scheduled task's pre-authorization (`AE-3.5`) may name.

    This **cannot** be a constant. External tools are named ``external_{slug}_{tool}``
    from the operator's own registered servers and configured connectors, so the set
    changes when they register one — a hand-maintained list would reject a perfectly
    valid scope and, worse, would silently stop covering tools added later. It had
    already drifted: mail send/reply and the vault reads landed approval-gated this
    sprint and never reached the old constant.

    Three sources, one list:

    - **statically marked** — ``requires_approval=True`` on the tool itself, read off the
      live registry the agent runs against, so a new one is covered the day it lands;
    - **conditionally gated** — :data:`_CONDITIONALLY_GATED`, which raise at call time and
      therefore can't be discovered by inspection;
    - **external** — read from the operator's own sources.

    The external half reads the cached catalog (both services list from the database), so
    this never dials a server. A tool the operator has already marked *trusted* is still
    listed: trust is revocable, and a scope that vanished from the vocabulary the moment
    it stopped gating would fail validation the moment it was revoked.
    """
    static = {t.name for t in tool_catalog(categories)}
    scopes = [
        t
        for t in tool_catalog(categories)
        if _is_statically_gated(t, categories) or t.name in _CONDITIONALLY_GATED
    ]
    # A conditionally-gated name that no longer matches a registered tool is a stale
    # constant, not a scope — surfacing it would offer the operator a checkbox that grants
    # nothing. The set is small and pinned by a test, so this is a guard, not a filter.
    scopes = [t for t in scopes if t.name in static]
    if external is not None:
        scopes.extend(await _external_scopes(external, owner_id))
    return sorted(scopes, key=lambda t: (t.category, t.name))


def _is_statically_gated(
    info: ToolInfo, categories: Mapping[str, AbstractToolset[RunDeps]] | None
) -> bool:
    """Whether the tool behind ``info`` carries ``requires_approval=True``."""
    cats = dict(categories) if categories is not None else toolsets.default_categories()
    toolset = cats.get(info.category)
    tool = getattr(toolset, "tools", {}).get(info.name.removeprefix(f"{info.category}_"))
    return bool(getattr(tool, "requires_approval", False))


async def _external_scopes(external: ExternalTools, owner_id: str) -> list[ToolInfo]:
    """The operator's external tools, named the way the model sees them.

    ``external_{slug}_{tool}`` mirrors how `tools/external.py` composes them — the
    category prefix, then the source's slug, then the tool's own name. Read from each
    service's stored catalog rather than by connecting, so listing the vocabulary costs
    a database read and never a process spawn or an HTTP handshake.
    """
    scopes: list[ToolInfo] = []
    for server in await external.mcp.list(owner_id):
        for tool in server.tools:
            scopes.append(
                ToolInfo(
                    name=f"external_{server.slug}_{tool.name}",
                    category="external",
                    description=_flatten(f"{server.name}: {tool.description}"),
                )
            )
    for connector in await external.integrations.list(owner_id):
        for action in connector.actions:
            scopes.append(
                ToolInfo(
                    name=f"external_{connector.slug}_{action.name}",
                    category="external",
                    description=_flatten(f"{connector.name}: {action.description}"),
                )
            )
    return scopes
