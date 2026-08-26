"""The `agents` category — delegating a self-contained piece of work to a sub-agent.

One coarse tool, `delegate_task(agent_name, task)`, from `pydantic_ai_harness`'s
`SubAgents`. The grain is the point: a catalog of many narrow tools costs the model
accuracy, and a single parameterised delegate keeps the whole capability to one entry.

Three things here are ours rather than the library's, each for a reason:

**Registered as a toolset, not a capability.** The capability form contributes its own
instructions and would put the tool outside the namespaced, operator-toggleable catalog
whose whole promise is that the settings list and the agent's real stack cannot diverge.
The delegate listing the capability form injects is re-delivered through the
`InstructionProvider` seam instead — it is small and static, so the prompt head is the
right home for it.

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

import logging
from collections import OrderedDict
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

_EXPLORER_INSTRUCTIONS = (
    "Explore the workspace and answer the question you are given with concrete file "
    "paths and quoted evidence. Do not modify anything — you have read-only access. "
    "Be thorough but report only what you actually found."
)


def delegate_instructions(_ctx: RunContext[RunDeps]) -> str:
    """The static listing the capability form would have injected. Registered through
    the manifest's `instructions` seam so it lands in the cached prompt prefix rather
    than churning per turn."""
    return (
        "You can delegate a self-contained piece of work to a sub-agent with "
        f"`agents_delegate_task`. Available: `{EXPLORER}` — searches and reads the "
        "workspace and reports back with concrete paths and evidence, without changing "
        "anything.\n"
        "Delegate when a question needs a lot of reading to answer and the reading "
        "itself is not what the operator wants to see; the sub-agent runs with its own "
        "history, so the task you give it must stand alone. Do not delegate work you "
        "can do in one or two tool calls — the round trip costs more than it saves."
    )


class _ConversationAgentsToolset(AbstractToolset[RunDeps]):
    """`SubAgents`, rebound to this run's workspace, model and event stream.

    The template exists only so `get_tools` can answer without a binding — the tool's
    name, description and schema do not depend on which workspace the explorer reads or
    which model it runs on, which is what keeps the operator's catalog identical to the
    agent's real stack.
    """

    def __init__(self, template: AbstractToolset[RunDeps]) -> None:
        self._template = template
        self._bound: OrderedDict[tuple[str, str], AbstractToolset[RunDeps]] = OrderedDict()

    @property
    def id(self) -> str:
        return "agents"

    @property
    def tools(self) -> dict[str, Any]:
        """The static registry `tools/catalog.py` enumerates for the settings surface.
        Without it this category contributes no rows and the operator cannot switch
        delegation off — the catalog reads this, not `get_tools`."""
        return self._template.tools

    async def get_tools(self, ctx: RunContext[RunDeps]) -> dict[str, ToolsetTool[RunDeps]]:
        return await self._template.get_tools(ctx)

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
        key = (workspace, str(background.model))
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

    The sandbox workspace in chat mode, the project's worktree in coding mode. It goes
    through `run_workspace` rather than reaching for a sandbox path so the explorer can
    never end up looking at a different filesystem than the agent that delegated to it.
    """
    try:
        workspace = await run_workspace(ctx)
    except WorktreeBusyError:
        # Another coding conversation holds the checkout; there is nothing to read.
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
