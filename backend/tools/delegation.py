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
from dataclasses import replace
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.toolsets import ToolsetTool

from runs import ToolProgress
from tools.deps import RunDeps

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


def stream_handler(ctx: RunContext[RunDeps], name: str) -> Any:
    """A sub-agent's events, flattened onto the parent's `tool.progress`.

    One short line per event, because `partial` is a string — the frozen run protocol has
    no nested shape and does not need one. Best-effort: a delegation must not fail because
    its narration did.
    """

    async def stream(sub_ctx: RunContext[Any], events) -> None:
        async for event in events:
            try:
                # Not awaited: `Run.emit` stamps and fans out synchronously. Awaiting the
                # `Event` it returns raised a `TypeError` straight into the guard below,
                # which is exactly how a delegation stayed silent while looking narrated.
                ctx.deps.run.emit(
                    ToolProgress(
                        tool_call_id=ctx.tool_call_id or "delegate",
                        partial=_describe(event, name),
                    )
                )
            except Exception:  # noqa: BLE001 — narration is never load-bearing
                logger.debug("delegate: dropped a sub-agent event", exc_info=True)

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
