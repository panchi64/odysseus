"""The `subagents` category — handing a self-contained piece of work to another agent.

Two tools, and the shape of them is the design.

**`launch` does not wait.** A sub-agent runs as its own Run on the same substrate and
takes minutes. Blocking this turn on it would spend the turn's whole step budget watching
a progress bar — which is exactly what the delegation this replaced did, and the reason a
five-minute sub-agent used to mean a five-minute silence. So `launch` returns the moment
the run is submitted, and says so in words: the model can launch several in one step,
carry on, and end its turn. It is told what each one found as each one finishes.

**The roster is generated, not written.** The one place the model reads what it may launch
is this tool's description, because that is where it is deciding — a standing instruction
at the prompt head would say the same thing a second time inside the cached prefix, and
say it furthest from the choice. Generating it from the roster is what stops the classic
failure: a hand-written list naming sub-agents that no longer exist and omitting the ones
that do, with nothing to make the two disagree loudly.

**Only a sub-agent that can write is gated.** Reading changes nothing, and asking about it
would be a question with one sensible answer asked over and over. One that edits does work
the operator's own merge will carry out, so launching it is theirs to allow — once per
conversation, if they grant it that far.
"""

from __future__ import annotations

from pydantic_ai import FunctionToolset, ModelRetry, RunContext
from pydantic_ai.exceptions import ApprovalRequired

from services.permissions import STRICTEST_PERMISSION
from services.subagents import (
    SubagentLauncher,
    SubagentParent,
    SubagentSpec,
    SubagentUnavailableError,
    builtin_roster,
    describe_roster,
)
from tools.deps import RunDeps
from tools.workspace import run_workspace

#: The conditionally-gated name this category contributes to the approval-scope
#: vocabulary. The raise below parks the run either way, but a name absent from the
#: assembled gated set never reaches the approval scopes, so the operator could not grant
#: it for the conversation and would be asked once per launch.
GATED_TOOLS: frozenset[str] = frozenset({"subagents_launch"})

_UNAVAILABLE = "Sub-agents are unavailable in this deployment."

_LAUNCH_DOC = """Hand a self-contained piece of work to a sub-agent, which does it on its own.

{roster}

It returns **immediately**, as soon as the sub-agent is submitted — it does not wait, and
you must not poll for it in a loop. Launch as many as the work genuinely splits into (issue
the calls together and they start together), then carry on with whatever does not depend on
them, and end your turn when nothing is left. **You will be told what each sub-agent found
as it finishes**, and you can keep working then.

Launch one when a piece of work needs a lot of reading or a lot of editing and the steps
themselves are not what the operator wants to see. Do not launch one for work you could do
in a couple of tool calls: the round trip costs more than it saves.

`task` has to stand alone. The sub-agent starts from an empty history and never sees this
conversation, so say what to do, where to start, and what a finished answer looks like. A
task that refers to "the bug we discussed" describes nothing it can act on.

`isolate` gives the sub-agent its own copy of the workspace, merged back when it finishes,
instead of working in the same files as you. Ask for it when you intend to keep editing
meanwhile — two agents in one working tree is fine when one of them is waiting and a mess
when neither is. It costs a copy, and a file you both changed comes back as a reported
conflict rather than silently taking one side.
"""


def subagents_toolset() -> FunctionToolset[RunDeps]:
    toolset = FunctionToolset[RunDeps]()

    async def launch(
        ctx: RunContext[RunDeps], agent_name: str, task: str, isolate: bool = False
    ) -> dict:
        launcher = ctx.deps.caps.get_optional(SubagentLauncher)
        if launcher is None:
            return {"launched": False, "detail": _UNAVAILABLE}
        roster = builtin_roster()
        spec = roster.get(agent_name)
        if spec is None:
            # Recoverable: the model very likely guessed a name. Naming the roster back
            # costs one retry, where failing the turn costs the whole thing.
            raise ModelRetry(
                f"There is no sub-agent called {agent_name!r}. Choose one of: "
                f"{', '.join(sorted(roster))}."
            )
        # Before anything else, and only for one that can change things: a launch that
        # ends in edits is the operator's to allow, and asking after a workspace has been
        # forked for it would be a side effect they never approved.
        if _can_write(spec) and not ctx.tool_call_approved:
            raise ApprovalRequired()
        try:
            started = await launcher.launch(
                ctx.deps.owner_id,
                spec,
                task,
                parent=await _parent(ctx),
                isolate=isolate,
            )
        except SubagentUnavailableError as exc:
            # A state the system is in, not a bug — hand it back so the model can adapt
            # (do the work itself, or tell the operator what to switch on).
            return {"launched": False, "detail": str(exc)}
        return {
            "launched": True,
            "subagent_id": started.subagent_id,
            "agent_name": started.name,
            "detail": (
                "Running on its own. Do not wait for it and do not poll — you will be "
                "told what it found when it finishes. Carry on, or end your turn."
            ),
        }

    launch.__doc__ = _LAUNCH_DOC.format(roster=describe_roster(builtin_roster()))
    toolset.add_function(launch, name="launch", requires_approval=True)

    @toolset.tool(name="read")
    async def read_subagent(ctx: RunContext[RunDeps], subagent_id: str) -> dict:
        """Check on a sub-agent you launched — whether it is still going, and what it has
        said so far.

        You do not need this to receive a sub-agent's report: a finished sub-agent tells
        you itself. Use it when you need to know *now* whether one is still working — a
        `running` status means it is, and calling this again in a loop will not make it
        finish sooner.
        """
        launcher = ctx.deps.caps.get_optional(SubagentLauncher)
        if launcher is None:
            return {"available": False, "detail": _UNAVAILABLE}
        try:
            view = await launcher.read(ctx.deps.owner_id, subagent_id)
        except SubagentUnavailableError as exc:
            raise ModelRetry(str(exc)) from exc
        return {
            "available": True,
            "subagent_id": view.subagent_id,
            "agent_name": view.name,
            "status": view.status,
            "report": view.summary,
            "error": view.error,
        }

    return toolset


def _can_write(spec: SubagentSpec) -> bool:
    """Whether launching this sub-agent is something the operator should rule on.

    Read off the spec's own ceiling rather than from a list of names, so a sub-agent a
    project declares is gated by what it can actually do rather than by whether anyone
    remembered to add it somewhere.
    """
    return spec.permission_ceiling != STRICTEST_PERMISSION


async def _parent(ctx: RunContext[RunDeps]) -> SubagentParent:
    """What the launching thread hands the sub-agent.

    Every field narrows it. The permission level rides along because the operator approved
    *this* thread at *that* level, and a sub-agent must not quietly come up with more rope
    than the one that asked for it. The workspace key rides along because that is what
    decides which files it works in — read off the run's own deps rather than re-derived,
    so a sub-agent cannot end up on a different filesystem than the agent that launched it.
    """
    try:
        workspace = await run_workspace(ctx)
    except Exception:
        # A workspace that will not open is a reason to launch without one, never a
        # reason to refuse the launch — the launcher decides whether the spec survives it.
        workspace = None
    return SubagentParent(
        conversation_id=ctx.deps.conversation_id,
        project_id=ctx.deps.project_id,
        mode=ctx.deps.mode,
        permission=ctx.deps.permission,
        workspace_from=workspace.root if workspace is not None else None,
        workspace_key=ctx.deps.workspace_key,
        run_id=ctx.deps.run.id,
    )
