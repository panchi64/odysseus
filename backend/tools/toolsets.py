"""The toolset access-policy stack — *our* policy over Pydantic AI primitives.

Which tools a run sees is composition, not bespoke machinery (the most leveraged
mapping in the design). Each category toolset is namespaced for stable
``category_tool`` names, combined, then passed through the **enabled gate** so an
operator-disabled tool is never offered. There is deliberately **no relevance
pre-filter** — a capable native-tool-calling model on one host discerns its own
tools; and with a single operator (no privilege tiers) there is no privilege
gate either.

The category registry is not a central list: this module owns only the **core**
categories (the builtin starter tools and the sandbox code runner, both wired by
``app.py`` itself). Every feature category arrives from its own manifest's
``toolsets`` export and is folded in at app assembly — the assembled mapping is
what production passes down as ``categories``.

Sensitive-action gating is *not* a filter here — those tools pause for operator
approval at execution time, handled by the engine, not dropped from the catalog. What
*is* here is the **approval gate**: the run's permission level marks every tool that
reaches past its write scope as needing approval, so the model's request for one comes
back to the engine undone instead of running. A tool's own marking is left alone — the
gate only ever adds (``services/permissions``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from pydantic_ai import AbstractToolset, CombinedToolset, RunContext, ToolDefinition

from services.permissions import beyond_scope

from .agents import agents_toolset
from .builtin import builtin_toolset
from .code import code_toolset
from .deps import RunDeps
from .files import files_toolset
from .plan import plan_toolset
from .repo import repo_toolset
from .shell import GATED_TOOLS as _SHELL_GATED
from .shell import shell_toolset

#: Conditionally-gated names the **core** categories contribute — the ones that raise
#: `ApprovalRequired` from inside the call rather than carrying `requires_approval=True`,
#: which no amount of inspection can discover. A feature category declares its own on its
#: manifest; the core ones have no manifest, so they are collected here and seeded into
#: `app.state.gated_tools` at assembly. A name missing from that union is missing from the
#: operator's approval-scope vocabulary, which is what makes a grant possible.
CORE_GATED_TOOLS: frozenset[str] = _SHELL_GATED


def _enabled_gate(ctx: RunContext[RunDeps], tool_def: ToolDefinition) -> bool:
    """Operator-disabled tools are not offered to or invoked by the agent."""
    return tool_def.name not in ctx.deps.disabled_tools


def _approval_gate(
    ctx: RunContext[RunDeps], tool_defs: list[ToolDefinition]
) -> list[ToolDefinition]:
    """Mark every tool that reaches past this run's permission level as needing approval.

    The level's half of the enforcement. Pydantic AI defers a call to an ``unapproved``
    tool rather than executing it — the same mechanism a tool's own
    ``requires_approval=True`` uses — so the engine gets the call, with its arguments,
    before anything happens, and rules on it (``services/permissions/decide.py``).

    **Rewriting the definition rather than filtering it out** is what separates this from
    the enabled gate above. A withheld tool tells the model the capability does not exist;
    a gated one tells it the capability needs permission, which is the true statement at
    every level except Plan — and Plan does its withholding in the catalog, where the
    saving in schema tokens is real.

    Only ``function`` tools are touched. An ``output`` tool ends the run and an
    ``external`` one is already deferred to someone else; making either "unapproved" would
    change what the deferral *means* rather than merely when it happens.
    """
    return [
        replace(tool_def, kind="unapproved")
        if tool_def.kind == "function"
        and beyond_scope(ctx.deps.permission, tool_def.name)
        else tool_def
        for tool_def in tool_defs
    ]


def core_categories() -> dict[str, AbstractToolset[RunDeps]]:
    """The categories the harness itself contributes — everything else is a manifest's."""
    return {
        "builtin": builtin_toolset(),
        "code": code_toolset(),
        "files": files_toolset(),
        "plan": plan_toolset(),
        # Core rather than a manifest's, for the same reason `plan` and `files` are: it
        # is bound to the run's own workspace, which no feature owns.
        "agents": agents_toolset(),
        # Coding mode's two categories. Registered unconditionally like every other, and
        # withheld from a chat run by `mode_disabled_tools` rather than by assembling a
        # different mapping — one catalog, so the operator's settings list and the
        # agent's real stack cannot diverge (`services/tool_policy.py`).
        "shell": shell_toolset(),
        "repo": repo_toolset(),
    }


def build_agent_toolsets(
    categories: Mapping[str, AbstractToolset[RunDeps]] | None = None,
) -> list[AbstractToolset[RunDeps]]:
    """Compose the gated, namespaced toolset stack handed to the Agent.

    ``categories`` is the assembled mapping (core + every manifest's export);
    ``None`` — a stateless/test turn that passed nothing — composes the core
    categories only.
    """
    cats = dict(categories) if categories is not None else core_categories()
    prefixed = [toolset.prefixed(name) for name, toolset in cats.items()]
    combined = CombinedToolset(prefixed)
    # Namespaced, then filtered, then gated — in that order because each step needs the
    # one before it: the gate classifies by the `category_tool` name the prefixing
    # produces, and there is no point gating a tool the filter already took away.
    return [combined.filtered(_enabled_gate).prepared(_approval_gate)]
