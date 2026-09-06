"""The `agents` category — delegating a self-contained piece of work to a sub-agent.

One coarse tool, `delegate_task(agent_name, task)`. The grain is the point: a catalog of
many narrow tools costs the model accuracy, and a single parameterised delegate keeps the
whole capability to one entry. Two sub-agents answer to it — an `explorer` that reads,
built here on the harness's `SubAgents`, and a `worker` that changes things in its own
fork of the workspace, which the harness cannot host and `tools/worker.py` runs instead.

Three things here are ours rather than the library's, each for a reason:

**Registered as a toolset, not a capability.** The capability form contributes its own
instructions and would put the tool outside the namespaced, operator-toggleable catalog
whose whole promise is that the settings list and the agent's real stack cannot diverge.

**Rebound per conversation.** `SubAgentToolset` defines no `for_run`, so the default
returns the same instance to every run — and the instance is where the sub-agents' roots
and the event handler live. A shared one would hand every thread the first thread's
bindings and stream a sub-agent's progress onto a dead run. The rebinding is the pattern
`files.py` established: answer `get_tools` from a root-independent template, and
re-resolve from a correctly-bound instance inside `call_tool`.

**Only the writer is gated.** Reading changes nothing, and asking about it would be a
question with one sensible answer asked over and over; a worker edits files the operator's
own merge will later carry out, so delegating to one is approved — once per conversation,
if they grant it that far.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any

from pydantic_ai import Agent, RunContext
from pydantic_ai.exceptions import ApprovalRequired
from pydantic_ai.toolsets import AbstractToolset, ToolsetTool
from pydantic_ai_harness import FileSystem, SubAgent, SubAgents

from services.projects.worktree import WorktreeBusyError
from services.registry import ModelRegistry
from services.workspace import RunWorkspace
from tools.delegation import (
    AGENT_NAME_ARG,
    DELEGATE_TOOL,
    EXPLORER,
    WORKER,
    redescribed_def,
    redescribed_tool,
    stream_handler,
)
from tools.deps import RunDeps
from tools.worker import MAX_WORKERS_PER_RUN, run_worker
from tools.workspace import run_workspace

# Bound toolsets are cached per (workspace, model) because building one registers the
# sub-agents and generates their schemas. Small and bounded — one entry per live
# conversation in practice.
_MAX_CACHED = 32

#: The conditionally-gated name this category contributes to the approval-scope
#: vocabulary. The raise below parks the run either way, but a name absent from
#: `app.state.gated_tools` never reaches `tools/catalog.approval_scopes`, so the operator
#: could not grant it for the conversation and would be asked once per delegation.
GATED_TOOLS = frozenset({f"agents_{DELEGATE_TOOL}"})

#: The explorer as the library registers it — the same line in the template and in the
#: binding, which is the only way those two can agree.
_EXPLORER_DESCRIPTION = (
    "Explore the workspace and answer questions about it without modifying anything"
)

_EXPLORER_INSTRUCTIONS = (
    "Explore the workspace and answer the question you are given with concrete file "
    "paths and quoted evidence. Do not modify anything — you have read-only access. "
    "Be thorough but report only what you actually found."
)

_NO_WORKSPACE = (
    "Delegation is unavailable: this conversation has no workspace for a sub-agent to "
    "work in."
)

_SPENT = (
    f"You have already set {MAX_WORKERS_PER_RUN} workers going this turn, which is the "
    "limit — each one forks the whole workspace. Do the rest of the work yourself, or "
    "report where you got to and let the operator ask for more."
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
        self._bound: OrderedDict[
            tuple[str, str, str], AbstractToolset[RunDeps]
        ] = OrderedDict()
        # run id -> workers set going in it. Bounded like the bindings above: a
        # long-lived process must not retain a counter per run it ever served.
        self._workers: OrderedDict[str, int] = OrderedDict()

    @property
    def id(self) -> str:
        return "agents"

    @property
    def tools(self) -> dict[str, Any]:
        """The static registry `tools/catalog.py` enumerates for the settings surface.
        Without it this category contributes no rows and the operator cannot switch
        delegation off — the catalog reads this, not `get_tools`."""
        return {name: redescribed_tool(name, tool) for name, tool in self._template.tools.items()}

    async def get_tools(self, ctx: RunContext[RunDeps]) -> dict[str, ToolsetTool[RunDeps]]:
        tools = await self._template.get_tools(ctx)
        return {name: redescribed_def(name, tool) for name, tool in tools.items()}

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext[RunDeps],
        tool: ToolsetTool[RunDeps],
    ) -> Any:
        wanted = str(tool_args.get(AGENT_NAME_ARG) or "")
        # Before anything else, and only for the writer: a delegation that ends in edits
        # is the operator's to allow, and asking after a container has been forked for it
        # would be a side effect they never approved.
        if wanted == WORKER and not ctx.tool_call_approved:
            raise ApprovalRequired()

        registry = ctx.deps.caps.get_optional(ModelRegistry)
        if registry is None:
            return "Delegation is unavailable: no model registry is configured."
        try:
            background = await registry.resolve_background(owner_id=ctx.deps.owner_id)
        except Exception as exc:  # noqa: BLE001 — degrade, don't fail the turn
            return f"Delegation is unavailable: {exc}"

        workspace = await _workspace_for(ctx)
        if workspace is None:
            return _NO_WORKSPACE

        if wanted == WORKER:
            if not self._claim_worker(ctx.deps.run.id):
                return _SPENT
            return await run_worker(
                ctx,
                workspace,
                task=str(tool_args.get("task") or ""),
                background=background,
                stream=stream_handler(ctx, WORKER),
            )

        bound = self._bind(str(workspace.root), background, ctx)
        tools = await bound.get_tools(ctx)
        resolved = tools.get(name)
        if resolved is None:  # pragma: no cover — the template and binding agree
            return f"Unknown delegate tool {name!r}."
        # Pydantic AI dispatches through the tool's own call_func, so delegating the
        # call alone would still run against the template's bindings.
        return await bound.call_tool(name, tool_args, ctx, resolved)

    def _claim_worker(self, run_id: str) -> bool:
        """Whether this run may set one more worker going, counting it if so."""
        spent = self._workers.get(run_id, 0)
        if spent >= MAX_WORKERS_PER_RUN:
            return False
        self._workers[run_id] = spent + 1
        self._workers.move_to_end(run_id)
        while len(self._workers) > _MAX_CACHED:
            self._workers.popitem(last=False)
        return True

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

        explorer = Agent[RunDeps, Any](
            background.model,
            name=EXPLORER,
            description=_EXPLORER_DESCRIPTION,
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
            event_stream_handler=stream_handler(ctx, EXPLORER),
        ).get_toolset()

        self._bound[key] = bound
        self._bound.move_to_end(key)
        while len(self._bound) > _MAX_CACHED:
            self._bound.popitem(last=False)
        return bound


async def _workspace_for(ctx: RunContext[RunDeps]) -> RunWorkspace | None:
    """Where the sub-agent works — the *parent's* workspace, resolved the one way.

    The sandbox workspace in a sandbox mode, the project's worktree in code mode. It goes
    through `run_workspace` rather than reaching for a sandbox path so a sub-agent can
    never end up on a different filesystem than the agent that delegated to it — the
    explorer reads it, and a worker is handed a fork of it.
    """
    try:
        return await run_workspace(ctx)
    except WorktreeBusyError:
        # Another code conversation holds the checkout; there is nothing to work in.
        return None


def agents_toolset() -> AbstractToolset[RunDeps]:
    """The template's bindings are never used — only `call_tool` acts, and it always
    rebinds first."""
    template = SubAgents[RunDeps](
        agents=[
            SubAgent(
                Agent[RunDeps, Any](
                    "test",
                    name=EXPLORER,
                    description=_EXPLORER_DESCRIPTION,
                )
            )
        ],
        agent_folders=None,
        inherit_tools=False,
    ).get_toolset()
    assert template is not None  # one sub-agent is configured, so there is a toolset
    return _ConversationAgentsToolset(template)
