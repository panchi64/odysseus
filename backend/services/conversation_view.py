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


def project_messages(messages: list[Any]) -> list[MessageView]:
    """Fold a ModelMessage history into ordered user/assistant view turns.

    Tool calls surface on the assistant turn that issued them; a later request's
    ``ToolReturnPart``/``RetryPromptPart`` mutates the same (shared) ``ToolView``
    that's already attached to its turn, so results stitch back in place.
    """
    views: list[MessageView] = []
    by_call: dict[str, ToolView] = {}
    for message in messages:
        if isinstance(message, ModelRequest):
            for part in message.parts:
                if isinstance(part, UserPromptPart):
                    views.append(
                        MessageView(
                            role="user",
                            content=_user_text(part.content),
                            timestamp=getattr(part, "timestamp", None),
                        )
                    )
                elif isinstance(part, ToolReturnPart):
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
            view = MessageView(role="assistant", timestamp=getattr(message, "timestamp", None))
            for part in message.parts:
                if isinstance(part, TextPart):
                    view.content += part.content
                elif isinstance(part, ThinkingPart):
                    view.reasoning += part.content
                elif isinstance(part, ToolCallPart):
                    tool = ToolView(
                        id=part.tool_call_id, name=part.tool_name, args=part.args_as_dict()
                    )
                    view.tools.append(tool)
                    by_call[part.tool_call_id] = tool
            views.append(view)
    return views
