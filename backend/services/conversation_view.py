"""Project a conversation's ``ModelMessage`` history into a render-ready view.

The durable record stores full-fidelity Pydantic AI ``ModelMessage`` blobs so a
cold session rehydrates exactly. The frontend needs a flat shape instead: an
ordered list of user/assistant turns, each assistant turn carrying its reasoning
split out from its answer and its tool calls stitched to their results.

This is the static-history counterpart to the live translator in
``agent/translate.py`` — the same part→domain mapping, applied to a settled
message list rather than a stream. Both share ``core.serde.jsonable`` for the
tool-result coercion; the shared helper lives in ``core`` so this lower layer
need not import the orchestrator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic_ai import (
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from core.serde import jsonable


@dataclass
class ToolView:
    id: str
    name: str
    args: dict[str, Any]
    status: str = "running"  # "running" | "ok" | "error"
    result: Any = None
    error: str | None = None


@dataclass
class MessageView:
    role: str  # "user" | "assistant"
    content: str = ""
    reasoning: str = ""
    tools: list[ToolView] = field(default_factory=list)
    timestamp: datetime | None = None
    # The model that produced this assistant turn (the last response's model_name —
    # the one that wrote the answer). None for user turns and turns older than this
    # projection. Surfaced so the UI can show what a chat actually last ran on.
    model: str | None = None
    # The id of the tree node that *defines this turn's branch point* — the user
    # request for a user turn, the first response for an assistant turn. It is what
    # the frontend addresses to regenerate / edit / delete / switch this turn.
    id: str = ""
    # Position among this turn's sibling versions (0-based) and how many there are.
    # 1 ⇒ no alternatives; >1 ⇒ the turn has been regenerated/edited.
    version_index: int = 0
    version_count: int = 1
    # The operator's durable pin on this turn (a bookmark), from the branch node.
    pinned: bool = False


def _user_text(content: Any) -> str:
    """Flatten a user prompt's content (str or multimodal sequence) to text.

    A multimodal turn keeps its text parts; non-text parts (images, files) are
    represented by a single ``[attachment]`` marker so an image-only turn still
    renders as a turn rather than vanishing into an empty bubble. Defensive — the
    composer is text-only today, so this only guards future multimodal input."""
    if isinstance(content, str):
        return content
    if isinstance(content, list | tuple):
        text = " ".join(part for part in content if isinstance(part, str)).strip()
        if text:
            return text
        return "[attachment]" if content else ""
    return ""


def project_tree(nodes: list[tuple[str, Any]]) -> list[MessageView]:
    """Fold an active-path ``(node_id, ModelMessage)`` sequence into ordered
    user/assistant view turns.

    One turn = one view. A user turn is a request carrying a ``UserPromptPart``.
    An assistant turn is the run of everything after it until the next user turn —
    one or more ``ModelResponse`` messages plus the interleaved tool-return
    requests — **merged into a single assistant view** (reasoning, then tool calls
    stitched to their results, then the answer). This matches the live stream,
    which renders one assistant bubble per turn, so a cold read and a warm one look
    identical.

    Each view's ``id`` is the node that *defines the turn's branch point*: the user
    request for a user turn, the first response for an assistant turn — i.e. the
    node whose siblings are this turn's versions. Version index/count are filled in
    later by the store, which holds the tree.

    Tool calls surface on the assistant turn that issued them; a later request's
    ``ToolReturnPart``/``RetryPromptPart`` mutates the same (shared) ``ToolView``
    already attached, so results stitch back in place.
    """
    views: list[MessageView] = []
    by_call: dict[str, ToolView] = {}
    assistant: MessageView | None = None  # the open assistant turn, if any
    for node_id, message in nodes:
        if isinstance(message, ModelRequest):
            user_parts = [p for p in message.parts if isinstance(p, UserPromptPart)]
            if user_parts:
                # A new user turn closes any open assistant turn.
                assistant = None
                part = user_parts[0]
                views.append(
                    MessageView(
                        role="user",
                        content=_user_text(part.content),
                        timestamp=getattr(part, "timestamp", None),
                        id=node_id,
                    )
                )
                continue
            # A tool-return request: stitch results into the open assistant turn.
            for part in message.parts:
                if isinstance(part, ToolReturnPart):
                    tool = by_call.get(part.tool_call_id)
                    if tool is not None:
                        tool.status = "ok"
                        tool.result = jsonable(part.content)
                elif isinstance(part, RetryPromptPart):
                    tool = by_call.get(part.tool_call_id)
                    if tool is not None:
                        tool.status = "error"
                        tool.error = part.model_response()
        elif isinstance(message, ModelResponse):
            if assistant is None:
                # First response of the turn — its node id is the branch point.
                assistant = MessageView(
                    role="assistant", timestamp=getattr(message, "timestamp", None), id=node_id
                )
                views.append(assistant)
            # A turn can span several responses (tool round-trips); the last one
            # carrying a name is the model that wrote the final answer.
            assistant.model = getattr(message, "model_name", None) or assistant.model
            for part in message.parts:
                if isinstance(part, TextPart):
                    assistant.content += part.content
                elif isinstance(part, ThinkingPart):
                    assistant.reasoning += part.content
                elif isinstance(part, ToolCallPart):
                    tool = ToolView(
                        id=part.tool_call_id, name=part.tool_name, args=part.args_as_dict()
                    )
                    assistant.tools.append(tool)
                    by_call[part.tool_call_id] = tool
    return views
