"""The toolset access-policy stack — *our* policy over Pydantic AI primitives.

Which tools a run sees is composition, not bespoke machinery (the most leveraged
mapping in the design). Each category toolset is namespaced for stable
``category_tool`` names, combined, then passed through the **enabled gate** so an
operator-disabled tool is never offered. There is deliberately **no relevance
pre-filter** — a capable native-tool-calling model on one host discerns its own
tools; and with a single operator (no privilege tiers) there is no privilege
gate either.

Sensitive-action gating is *not* a filter here — those tools pause for operator
approval at execution time, handled by the engine, not dropped from the catalog.
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic_ai import AbstractToolset, CombinedToolset, RunContext, ToolDefinition

from .builtin import builtin_toolset
from .code import code_toolset
from .deps import RunDeps
from .memory import memory_toolset
from .preview import preview_toolset
from .search import web_toolset


def _enabled_gate(ctx: RunContext[RunDeps], tool_def: ToolDefinition) -> bool:
    """Operator-disabled tools are not offered to or invoked by the agent."""
    return tool_def.name not in ctx.deps.disabled_tools


def default_categories() -> dict[str, AbstractToolset[RunDeps]]:
    """The tool catalog grows here as services land (one category per cluster)."""
    return {
        "builtin": builtin_toolset(),
        "memory": memory_toolset(),
        "code": code_toolset(),
        "preview": preview_toolset(),
        "web": web_toolset(),
    }


def build_agent_toolsets(
    categories: Mapping[str, AbstractToolset[RunDeps]] | None = None,
) -> list[AbstractToolset[RunDeps]]:
    """Compose the gated, namespaced toolset stack handed to the Agent."""
    cats = dict(categories) if categories is not None else default_categories()
    prefixed = [toolset.prefixed(name) for name, toolset in cats.items()]
    combined = CombinedToolset(prefixed)
    return [combined.filtered(_enabled_gate)]
