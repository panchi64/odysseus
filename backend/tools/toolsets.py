"""The toolset access-policy stack — *our* policy over Pydantic AI primitives.

Which tools a run sees is composition, not bespoke machinery (the most leveraged
mapping in the design). Each category toolset is namespaced for stable
``category_tool`` names (D15), combined, then passed through the **enabled gate**
(AE-3.3). There is deliberately **no relevance pre-filter** — a capable native-
tool-calling model on one host discerns its own tools (D3); and with no
privilege tiers (single operator, D14) there is no privilege gate either.

Sensitive-action gating is *not* a filter here — those tools are approval-gated
at execution time (D20), handled by the engine, not by dropping them.
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic_ai import AbstractToolset, CombinedToolset, RunContext, ToolDefinition

from .builtin import builtin_toolset
from .deps import RunDeps


def _enabled_gate(ctx: RunContext[RunDeps], tool_def: ToolDefinition) -> bool:
    """AE-3.3: operator-disabled tools are not offered to or invoked by the agent."""
    return tool_def.name not in ctx.deps.disabled_tools


def default_categories() -> dict[str, AbstractToolset[RunDeps]]:
    """The tool catalog grows here as services land (one category per cluster)."""
    return {"builtin": builtin_toolset()}


def build_agent_toolsets(
    categories: Mapping[str, AbstractToolset[RunDeps]] | None = None,
) -> list[AbstractToolset[RunDeps]]:
    """Compose the gated, namespaced toolset stack handed to the Agent."""
    cats = dict(categories) if categories is not None else default_categories()
    prefixed = [toolset.prefixed(name) for name, toolset in cats.items()]
    combined = CombinedToolset(prefixed)
    return [combined.filtered(_enabled_gate)]
