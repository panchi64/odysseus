"""The `agents` category — delegating a self-contained piece of work to a sub-agent.

One coarse tool, `delegate_task(agent_name, task)`, from `pydantic_ai_harness`'s
`SubAgents`. The grain is the point: a catalog of many narrow tools costs the model
accuracy, and a single parameterised delegate keeps the whole capability to one entry.

Three things here are ours rather than the library's, each for a reason:

**Registered as a toolset, not a capability.** The capability form contributes its own
instructions and would put the tool outside the namespaced, operator-toggleable catalog
whose whole promise is that the settings list and the agent's real stack cannot diverge.
What that listing said — which sub-agents exist, and when a delegation is worth its round
trip — is folded into the tool's **own description** instead. It lived for a while as a
standing instruction beside the tool, which meant the prompt head and the tool schema each
carried a paragraph making the same point, both in the cached prefix, and a model reading
one of them right there in the catalog entry it is deciding about needs no second copy at
the head. Overriding the description is a two-line job done twice, because the name is read
from two places (`get_tools` for the model, `.tools` for the operator's catalog) and they
must not disagree. The `agent_name` **parameter** goes with it: the harness writes it
against the listing the capability form would have registered, so left alone it sends the
model hunting through instructions this app never writes for a roster that is sitting in
the description it just read.

**Rebound per conversation.** `SubAgentToolset` defines no `for_run`, so the default
returns the same instance to every run — and the instance is where the sub-agents' roots
and the event handler live. A shared one would hand every thread the first thread's
bindings and stream a sub-agent's progress onto a dead run. The rebinding is the pattern
`files.py` established: answer `get_tools` from a root-independent template so the
operator catalog stays identical, and re-resolve from a correctly-bound instance inside
`call_tool`.

**Sub-agent work is streamed.** `SubAgents` takes an `event_stream_handler`, but at
construction — which is the other half of why the instance must be per-run. Without it a
delegation is a multi-minute silent gap in the transcript. Events are flattened to one
short line on the parent's existing `tool.progress` frame (`partial` is a string), so the
frozen event protocol is untouched.
"""

from __future__ import annotations

import copy
import logging
from collections import OrderedDict
from dataclasses import replace
from typing import Any

from pydantic_ai import Agent, RunContext
from pydantic_ai.toolsets import AbstractToolset, ToolsetTool
from pydantic_ai_harness import FileSystem, SubAgent, SubAgents

from runs import ToolProgress
from services.projects.worktree import WorktreeBusyError
from services.registry import ModelRegistry
from tools.deps import RunDeps
from tools.workspace import run_workspace

logger = logging.getLogger(__name__)

# Bound toolsets are cached per (workspace, model) because building one registers the
# sub-agents and generates their schemas. Small and bounded — one entry per live
# conversation in practice.
_MAX_CACHED = 32

EXPLORER = "explorer"

#: The tool's own name inside the toolset; namespaced to `agents_delegate_task`.
DELEGATE_TOOL = "delegate_task"

#: The parameter naming which sub-agent runs, and what it is told to look at. The roster
#: is in :data:`DELEGATE_DESCRIPTION` directly above it in the offered schema; the
#: library's own text points at a standing listing this app does not register, and a
#: model that goes looking for one guesses a name and spends a retry on `Unknown
#: sub-agent`.
AGENT_NAME_ARG = "agent_name"
AGENT_NAME_DESCRIPTION = "One of the sub-agents named above."

#: What the model is told about delegating, in the one place it is deciding whether to.
#: Replaces the library's docstring-derived description, which describes the mechanism and
#: cannot know which sub-agents this installation registered.
DELEGATE_DESCRIPTION = (
    "Delegate a self-contained piece of work to a sub-agent and return what it reports. "
    f"Available: `{EXPLORER}` — searches and reads the workspace and reports back with "
    "concrete paths and quoted evidence, changing nothing.\n\n"
    "Delegate when a question needs a lot of reading to answer and the reading itself is "
    "not what the operator wants to see. The sub-agent runs with its own history and never "
    "sees this conversation, so `task` has to stand alone — say what to find, where to "
    "start, and what a useful answer looks like. Do not delegate work you can do in one or "
    "two tool calls: the round trip costs more than it saves."
)

_EXPLORER_INSTRUCTIONS = (
    "Explore the workspace and answer the question you are given with concrete file "
    "paths and quoted evidence. Do not modify anything — you have read-only access. "
    "Be thorough but report only what you actually found."
)


class _ConversationAgentsToolset(AbstractToolset[RunDeps]):
    """`SubAgents`, rebound to this run's workspace, model and event stream.

    The template exists only so `get_tools` can answer without a binding — the tool's
    name, description and schema do not depend on which workspace the explorer reads or
    which model it runs on, which is what keeps the operator's catalog identical to the
    agent's real stack. Both readings of it pass through :data:`DELEGATE_DESCRIPTION`, so
    what the model is offered and what the operator is shown say the same thing.
    """

    def __init__(self, template: AbstractToolset[RunDeps]) -> None:
        self._template = template
        self._bound: OrderedDict[
            tuple[str, str, str], AbstractToolset[RunDeps]
        ] = OrderedDict()

    @property
    def id(self) -> str:
        return "agents"

    @property
    def tools(self) -> dict[str, Any]:
        """The static registry `tools/catalog.py` enumerates for the settings surface.
        Without it this category contributes no rows and the operator cannot switch
        delegation off — the catalog reads this, not `get_tools`."""
        return {
            name: _redescribed_tool(name, tool) for name, tool in self._template.tools.items()
        }

    async def get_tools(self, ctx: RunContext[RunDeps]) -> dict[str, ToolsetTool[RunDeps]]:
        tools = await self._template.get_tools(ctx)
        return {name: _redescribed_def(name, tool) for name, tool in tools.items()}

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext[RunDeps],
        tool: ToolsetTool[RunDeps],
    ) -> Any:
        registry = ctx.deps.caps.get_optional(ModelRegistry)
        if registry is None:
            return "Delegation is unavailable: no model registry is configured."
        try:
            background = await registry.resolve_background(owner_id=ctx.deps.owner_id)
        except Exception as exc:  # noqa: BLE001 — degrade, don't fail the turn
            return f"Delegation is unavailable: {exc}"

        workspace = await _workspace_for(ctx)
        if workspace is None:
            return (
                "Delegation is unavailable: this conversation has no workspace for a "
                "sub-agent to read."
            )

        bound = self._bind(workspace, background, ctx)
        tools = await bound.get_tools(ctx)
        resolved = tools.get(name)
        if resolved is None:  # pragma: no cover — the template and binding agree
            return f"Unknown delegate tool {name!r}."
        # Pydantic AI dispatches through the tool's own call_func, so delegating the
        # call alone would still run against the template's bindings.
        return await bound.call_tool(name, tool_args, ctx, resolved)

    def _bind(
        self, workspace: str, background: Any, ctx: RunContext[RunDeps]
    ) -> AbstractToolset[RunDeps]:
        # Keyed by the **run**, not just the workspace and model, because the event
        # handler below closes over this `ctx`. A key that outlived the run would hand
        # the next delegation a handler pointed at a finished `Run` and a stale
        # `tool_call_id` — sub-agent progress would vanish from every delegation after
        # the first, and in code mode (one worktree per project) from another
        # conversation's entirely. A run makes several delegations, so the cache still
        # earns its keep within one.
        key = (workspace, str(background.model), ctx.deps.run.id)
        cached = self._bound.get(key)
        if cached is not None:
            self._bound.move_to_end(key)
            return cached

        async def stream(sub_ctx: RunContext[Any], events) -> None:
            """A sub-agent's events, flattened onto the parent's tool.progress.

            One short line per event, because `partial` is a string — the frozen run
            protocol has no nested shape and does not need one. Best-effort: a
            delegation must not fail because its narration did.
            """
            async for event in events:
                try:
                    await ctx.deps.run.emit(
                        ToolProgress(
                            tool_call_id=ctx.tool_call_id or "delegate",
                            partial=_describe(event),
                        )
                    )
                except Exception:  # noqa: BLE001 — narration is never load-bearing
                    logger.debug("delegate: dropped a sub-agent event", exc_info=True)

        explorer = Agent[RunDeps, Any](
            background.model,
            name=EXPLORER,
            description=(
                "Explore the workspace and answer questions about it without "
                "modifying anything"
            ),
            instructions=_EXPLORER_INSTRUCTIONS,
            model_settings=background.reasoning_off,
            capabilities=[FileSystem[RunDeps](workspace, read_only=True)],
        )
        bound = SubAgents[RunDeps](
            agents=[SubAgent(explorer)],
            agent_folders=None,
            # Off by default, and left off deliberately: it also excludes the delegate
            # tool itself, so a sub-agent cannot recurse into further delegation.
            inherit_tools=False,
            event_stream_handler=stream,
        ).get_toolset()

        self._bound[key] = bound
        self._bound.move_to_end(key)
        while len(self._bound) > _MAX_CACHED:
            self._bound.popitem(last=False)
        return bound


def _redescribed_tool(name: str, tool: Any) -> Any:
    """The catalog's `Tool`, carrying our description. Copied and mutated rather than
    `replace`d because `Tool` declares `init=False` with a hand-written constructor whose
    parameters are not its fields — feeding the fields back through it is a rewrite waiting
    to break on a library upgrade."""
    if name != DELEGATE_TOOL:
        return tool
    clone = copy.copy(tool)
    clone.description = DELEGATE_DESCRIPTION
    return clone


def _redescribed_def(name: str, tool: ToolsetTool[RunDeps]) -> ToolsetTool[RunDeps]:
    """The model's `ToolDefinition`, carrying our description and our parameter prose.

    Both halves are ordinary dataclasses here, so this one is a `replace`; the schema is
    copied rather than edited, since the toolset hands out the same object every call and
    the describing pass downstream reads it independently.
    """
    if name != DELEGATE_TOOL:
        return tool
    schema = copy.deepcopy(dict(tool.tool_def.parameters_json_schema))
    properties = schema.get("properties")
    if isinstance(properties, dict) and isinstance(properties.get(AGENT_NAME_ARG), dict):
        properties[AGENT_NAME_ARG]["description"] = AGENT_NAME_DESCRIPTION
    return replace(
        tool,
        tool_def=replace(
            tool.tool_def,
            description=DELEGATE_DESCRIPTION,
            parameters_json_schema=schema,
        ),
    )


def _describe(event: Any) -> str:
    """One line describing a sub-agent event. Deliberately forgiving: the library's
    event union grows, and an unrecognised event should read as activity, not crash the
    narration."""
    kind = type(event).__name__
    for attr in ("part", "delta", "result"):
        value = getattr(event, attr, None)
        if value is not None:
            text = str(value)
            return f"{EXPLORER}: {text[:160]}"
    return f"{EXPLORER}: {kind}"


async def _workspace_for(ctx: RunContext[RunDeps]) -> str | None:
    """Where the sub-agent reads — the *parent's* workspace, resolved the one way.

    The sandbox workspace in a sandbox mode, the project's worktree in code mode. It goes
    through `run_workspace` rather than reaching for a sandbox path so the explorer can
    never end up looking at a different filesystem than the agent that delegated to it.
    """
    try:
        workspace = await run_workspace(ctx)
    except WorktreeBusyError:
        # Another code conversation holds the checkout; there is nothing to read.
        return None
    return None if workspace is None else str(workspace.root)


def agents_toolset() -> AbstractToolset[RunDeps]:
    """The template's bindings are never used — only `call_tool` acts, and it always
    rebinds first."""
    template = SubAgents[RunDeps](
        agents=[
            SubAgent(
                Agent[RunDeps, Any](
                    "test",
                    name=EXPLORER,
                    description=(
                        "Explore the workspace and answer questions about it without "
                        "modifying anything"
                    ),
                )
            )
        ],
        agent_folders=None,
        inherit_tools=False,
    ).get_toolset()
    assert template is not None  # one sub-agent is configured, so there is a toolset
    return _ConversationAgentsToolset(template)
