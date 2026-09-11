"""Delegation as everyone outside it sees it: the roster, the tool's text, the progress.

Three readers, one source. The **model** reads the roster where it is deciding whether to
delegate — in the tool's own description, not in a standing instruction at the prompt head
that would say the same thing a second time inside the cached prefix. The **operator**
reads it in the catalog, which is a different code path (`.tools` rather than `get_tools`)
and therefore the classic place for a settings screen to end up describing a tool that no
longer works that way. The **transcript** reads a sub-agent's events while it runs, or a
delegation is a multi-minute silence.

The harness writes its own text for both of the first two, against a standing listing this
app deliberately does not register — so left alone it sends the model hunting for a roster
nothing writes, and it guesses a name. Grafting ours on is what the two rewrites below do,
and they live here together so the two readings cannot drift apart.
"""

from __future__ import annotations

import copy
import logging
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import replace
from typing import Any

from pydantic import BaseModel
from pydantic_ai import RunContext
from pydantic_ai.toolsets import ToolsetTool

from runs.events import (
    SUBAGENT_SUMMARY_LIMIT,
    SubagentCompleted,
    SubagentFailed,
    SubagentProgress,
    SubagentStarted,
    ToolProgress,
)
from tools.deps import RunDeps
from tools.emit import RunEventEmitted

logger = logging.getLogger(__name__)

#: The roster. One reads, one writes — and which is which is the whole of what the model
#: needs to pick between them.
EXPLORER = "explorer"
WORKER = "worker"

#: The tool's own name inside the toolset; namespaced to `agents_delegate_task`.
DELEGATE_TOOL = "delegate_task"

#: The parameter naming which sub-agent runs, and what it is told to do. The roster is in
#: :data:`DELEGATE_DESCRIPTION` directly above it in the offered schema; the library's own
#: text points at a standing listing this app does not register, and a model that goes
#: looking for one guesses a name and spends a retry on `Unknown sub-agent`.
AGENT_NAME_ARG = "agent_name"
AGENT_NAME_DESCRIPTION = "One of the sub-agents named above."

#: What the model is told about delegating, in the one place it is deciding whether to.
DELEGATE_DESCRIPTION = (
    "Delegate a self-contained piece of work to a sub-agent and return what it reports.\n\n"
    f"`{EXPLORER}` — searches and reads the workspace and reports back with concrete "
    "paths and quoted evidence, changing nothing.\n"
    f"`{WORKER}` — changes things, in its own copy of the workspace: it edits, runs and "
    "verifies there, and what it changed is then merged back into yours, with any "
    "conflict reported instead of overwriting your version. Say exactly what to change "
    "and how to verify it — you cannot correct a worker while it runs.\n\n"
    "Delegate when a piece of work needs a lot of reading or a lot of editing and the "
    "steps themselves are not what the operator wants to see. The sub-agent runs with its "
    "own history and never sees this conversation, so `task` has to stand alone — say "
    "what to do, where to start, and what a finished answer looks like. Do not delegate "
    "work you can do in one or two tool calls: the round trip costs more than it saves."
)


def redescribed_tool(name: str, tool: Any) -> Any:
    """The catalog's `Tool`, carrying our description. Copied and mutated rather than
    `replace`d because `Tool` declares `init=False` with a hand-written constructor whose
    parameters are not its fields — feeding the fields back through it is a rewrite waiting
    to break on a library upgrade."""
    if name != DELEGATE_TOOL:
        return tool
    clone = copy.copy(tool)
    clone.description = DELEGATE_DESCRIPTION
    return clone


def redescribed_def(name: str, tool: ToolsetTool[RunDeps]) -> ToolsetTool[RunDeps]:
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


#: The delegation the current task is inside, for the one reader that cannot be told.
#: `stream_handler` is built once per run — the explorer's binding caches it, long before
#: the delegation whose events it will carry exists — so the id cannot be closed over and
#: a lookup keyed on the call id would read the *first* delegation's. A context variable
#: is set by :func:`delegated` around the awaited child, which is exactly the scope the
#: handler runs in, and stays right when a turn has two delegations in flight at once.
_CURRENT: ContextVar[str | None] = ContextVar("odysseus_subagent", default=None)

#: Per-run delegation counter, bounded like every other cache a long-lived process keeps
#: per run. It is what makes a retried delegation a second sub-agent rather than the same
#: one reported twice: the model re-issuing a call reuses its `tool_call_id`, so the id
#: below would otherwise collide and two rows would fold into one that finished twice.
_SEQ: OrderedDict[str, int] = OrderedDict()
_MAX_RUNS = 64


def _next_seq(run_id: str) -> int:
    seq = _SEQ.get(run_id, 0) + 1
    _SEQ[run_id] = seq
    _SEQ.move_to_end(run_id)
    while len(_SEQ) > _MAX_RUNS:
        _SEQ.popitem(last=False)
    return seq


async def _announce(ctx: RunContext[RunDeps], body: BaseModel) -> None:
    """One structured frame about a sub-agent, best-effort.

    Guarded for the same reason the narration below is: an emit into a context with no
    stream raises, and a delegation that cannot be reported on must still delegate.
    """
    try:
        await ctx.emit(RunEventEmitted(body=body))
    except Exception:  # noqa: BLE001 — reporting is never load-bearing
        logger.debug("delegate: dropped a sub-agent frame", exc_info=True)


async def delegated(
    ctx: RunContext[RunDeps],
    agent_name: str,
    task: str,
    call: Callable[[], Awaitable[Any]],
) -> Any:
    """Run one delegation, bracketed by the frames a roster of sub-agents is built from.

    Wrapped around the *awaited child* rather than around the whole tool call, so a
    delegation that degrades before anything is delegated — no registry, no workspace, the
    worker budget spent — never opens a row for a sub-agent that does not exist.

    The close is in a `finally`, because a sub-agent that raises is precisely the case a
    row would otherwise sit on "running" forever: the ordinary failures here degrade to a
    sentence for the model, so anything that does escape is unusual and worth seeing end.
    """
    run_id = ctx.deps.run.id
    tool_call_id = ctx.tool_call_id or "delegate"
    subagent_id = f"{run_id}:{tool_call_id}:{_next_seq(run_id)}"
    await _announce(
        ctx,
        SubagentStarted(
            subagent_id=subagent_id,
            agent_name=agent_name,
            task=task,
            tool_call_id=tool_call_id,
        ),
    )
    began = time.monotonic()
    token = _CURRENT.set(subagent_id)
    outcome: BaseModel
    try:
        result = await call()
    except BaseException as exc:  # noqa: BLE001 — recorded, then re-raised untouched
        outcome = SubagentFailed(subagent_id=subagent_id, error=str(exc) or type(exc).__name__)
        raise
    else:
        outcome = SubagentCompleted(
            subagent_id=subagent_id,
            summary=str(result)[:SUBAGENT_SUMMARY_LIMIT],
            duration_ms=int((time.monotonic() - began) * 1000),
        )
        return result
    finally:
        _CURRENT.reset(token)
        await _announce(ctx, outcome)


def stream_handler(ctx: RunContext[RunDeps], name: str) -> Any:
    """A sub-agent's events, flattened onto the parent's `tool.progress` **and** carried
    as `subagent.progress`.

    Two frames per event, deliberately, because there are two readers and neither's is
    derivable from the other. The transcript wants one short line under the call that
    made it — `partial` is a string, the frozen run protocol has no nested shape there and
    does not need one. A roster of sub-agents wants the same line filed under *which*
    sub-agent said it, which the flattened form cannot say: every delegation on one tool
    call flattens onto the same `tool_call_id`.

    Both are best-effort, and separately so: a delegation must not fail because its
    narration did, and neither reader's frame is worth losing the other's.
    """

    async def stream(sub_ctx: RunContext[Any], events) -> None:
        async for event in events:
            line = _describe(event, name)
            try:
                # Awaited, unlike the `Run.emit` this replaced: `RunContext.emit` is a
                # coroutine and dropping it would leave the narration unsent. The guard
                # below still stands — an emit into a context with no stream raises, and
                # a delegation that cannot narrate must still delegate.
                await ctx.emit(
                    RunEventEmitted(
                        body=ToolProgress(
                            tool_call_id=ctx.tool_call_id or "delegate",
                            partial=line,
                        )
                    )
                )
            except Exception:  # noqa: BLE001 — narration is never load-bearing
                logger.debug("delegate: dropped a sub-agent event", exc_info=True)
            subagent_id = _CURRENT.get()
            if subagent_id is not None:
                await _announce(ctx, SubagentProgress(subagent_id=subagent_id, partial=line))

    return stream


def _describe(event: Any, name: str) -> str:
    """One line describing a sub-agent event. Deliberately forgiving: the library's event
    union grows, and an unrecognised event should read as activity, not crash the
    narration."""
    kind = type(event).__name__
    for attr in ("part", "delta", "result"):
        value = getattr(event, attr, None)
        if value is not None:
            text = str(value)
            return f"{name}: {text[:160]}"
    return f"{name}: {kind}"
