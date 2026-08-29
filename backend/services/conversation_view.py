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
from core.text import CHARS_PER_TOKEN


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
    # "compaction" is a chassis-authored divider, not a turn either party took: the
    # conversation was folded into a summary here (`content`), and the turns above it are
    # what the model now replays as that summary.
    role: str  # "user" | "assistant" | "compaction"
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
    # Upload ids the operator attached to this (user) turn — the frontend renders them
    # as file chips. Empty for assistant turns and turns sent without attachments.
    attachment_ids: list[str] = field(default_factory=list)
    # Set when the run behind this assistant turn ended `outcome: "blocked"` (a
    # usage/loop/context/time bound) — the human-readable reason. Filled in by the
    # store from the branch node, like `pinned`; None for every other turn.
    blocked_reason: str | None = None
    # `role="compaction"` only — what this divider actually cost, so the UI can say
    # "14 messages folded, ~62k → ~4k" without counting or estimating anything itself.
    # `messages_compacted` is how many messages the summary stands in for;
    # `tokens_before`/`tokens_after` are coarse `estimate_tokens` figures over the folded
    # messages and over the summary. The same three values ride the live
    # `conversation.compacted` event, computed the same way, so a live divider and the
    # one a reload draws report identical numbers. 0 on every other role.
    messages_compacted: int = 0
    tokens_before: int = 0
    tokens_after: int = 0


def estimate_tokens(messages: list[Any]) -> int:
    """A coarse token estimate for a list of messages, from its **text only**.

    The fallback for endpoints that report no usage — local servers commonly return
    ``input_tokens=0``, which ``services.conversations.context_footprint`` (rightly) treats
    as unmeasured rather than as a real zero. Without an estimate, conversation compaction
    would be dead on exactly the self-hosted endpoints this workspace is built for.

    Deliberately blind to binary parts. A retained inline image is base64 in the blob, and
    measuring it by character length would read a single screenshot as hundreds of
    thousands of phantom tokens and compact a thread that is nowhere near full. Ignoring
    image tokens under-counts instead — the safe direction, since the run's own
    context-overflow stop is still there behind this.

    It lives here rather than beside the compaction code that first needed it because the
    projection needs the same number: a compaction divider reports what it folded, and a
    cold read must report the same figure the live event did.

    ``messages`` is a list of ``ModelMessage``; typed loosely so this module keeps the
    same duck-typed part handling as the projection below."""
    chunks = (_message_text(message) for message in messages)
    return sum(len(text) for text in chunks if text) // CHARS_PER_TOKEN


@dataclass(frozen=True)
class ContentChars:
    """Message characters, split by how they tokenize.

    Prose and JSON do not tokenize at the same rate — measured against cl100k, prose runs
    about 4.7 characters per token and serialized JSON about 4.0, because JSON spends a
    third of its characters on punctuation and short repeated keys. A single
    characters-per-token proxy is fine for a *soft budget* (which is all
    :func:`estimate_tokens` serves) but not for a **split**, where a shared divisor
    silently inflates whichever part is prose by about a fifth relative to whichever part
    is JSON. Keeping the two apart is what lets ``services.context_budget`` apply the
    right rate to each."""

    prose: int
    structured: int


def message_chars(messages: list[Any]) -> ContentChars:
    """Characters across ``messages``, split prose vs. serialized-structure.

    The classification is by content shape, not by part type, because that is exactly the
    distinction that tokenizes differently: a string is prose wherever it appears, and a
    dict is JSON by the time the model sees it. Binary content contributes nothing, on
    the same grounds as :func:`estimate_tokens`."""
    prose = structured = 0
    for message in messages:
        for part in message.parts:
            content = getattr(part, "content", None)
            if isinstance(content, str):
                prose += len(content)
            elif isinstance(content, list | tuple) and all(
                isinstance(item, str) for item in content
            ):
                prose += sum(len(item) for item in content)
            else:
                structured += len(_content_text(content))
    return ContentChars(prose=prose, structured=structured)


def _message_text(message: Any) -> str:
    """Every text-bearing part of a message, joined — the input to
    :func:`estimate_tokens`. Binary content contributes nothing on purpose (see there)."""
    return " ".join(_content_text(getattr(part, "content", None)) for part in message.parts)


def _content_text(content: Any) -> str:
    """A part's content as the text a model would actually be sent.

    **Structured content counts.** A tool result is usually a dict — a search's hits, a
    file listing, a page of rows — and it reaches the model as serialized JSON, keys
    included. Reading only `str` content scored every one of those as zero, which on a
    tool-heavy thread is most of the window: the footprint fallback under-reported by
    multiples, so auto-compaction held off on precisely the threads filling up fastest,
    and the context breakdown credited the whole weight to the tool *schemas* instead of
    to the results they returned.

    **Anything unrecognised still counts as nothing**, which is what keeps the binary
    rule intact. A `BinaryContent` — a retained screenshot, base64 in the blob — falls
    through to `""` rather than being measured by its character length, because a single
    image would otherwise read as hundreds of thousands of phantom tokens. Under-counting
    is the safe direction and the run's own context-overflow stop is still behind this."""
    if isinstance(content, str):
        return content
    # `bool` before the numbers: it is an `int` subclass, and "True" is not what a model
    # is sent for a boolean field anyway.
    if isinstance(content, bool):
        return str(content)
    if isinstance(content, int | float):
        return str(content)
    if isinstance(content, dict):
        # Keys as well as values: they are serialized alongside the data and are a real
        # share of a wide row's tokens.
        return " ".join(
            f"{key} {_content_text(value)}" for key, value in content.items()
        )
    if isinstance(content, list | tuple):
        return " ".join(_content_text(item) for item in content)
    return ""


def flatten_content(content: Any) -> str:
    """Flatten a message part's content (str or multimodal sequence) to text.

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


def project_tree(
    nodes: list[tuple[str, Any]], *, compacted_ids: frozenset[str] = frozenset()
) -> list[MessageView]:
    """Fold an active-path ``(node_id, ModelMessage)`` sequence into ordered
    user/assistant view turns.

    ``compacted_ids`` names the conversation-compaction checkpoints among ``nodes``. Each
    becomes its own ``role="compaction"`` view — a divider carrying the summary — instead
    of the user turn its underlying ``UserPromptPart`` would otherwise read as. This stays
    purely order-driven: the caller hands the nodes in the order it wants them rendered.

    A checkpoint's divider also reports **what the fold cost** — how many messages it
    stands in for, and a coarse before/after token estimate — derived here rather than
    persisted. The caller hands the nodes in operator order, where a checkpoint sits
    immediately after the last node it covers, so the messages since the *previous*
    checkpoint (that checkpoint included) are exactly the set the fold replaced — the same
    set the live ``conversation.compacted`` event counted, so the two agree.

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
    # The messages a checkpoint would fold: everything since the previous one (which is
    # itself part of the set — a second fold summarizes the first summary plus what
    # followed it, exactly as `compaction_plan` collects them).
    since_checkpoint: list[Any] = []
    for node_id, message in nodes:
        if node_id in compacted_ids:
            # A conversation-compaction checkpoint: its own turn, not the operator's.
            # It closes any open assistant turn, exactly as a user turn would.
            assistant = None
            views.append(
                MessageView(
                    role="compaction",
                    content=flatten_content(message.parts[0].content) if message.parts else "",
                    timestamp=getattr(message.parts[0], "timestamp", None)
                    if message.parts
                    else None,
                    id=node_id,
                    messages_compacted=len(since_checkpoint),
                    tokens_before=estimate_tokens(since_checkpoint),
                    tokens_after=estimate_tokens([message]),
                )
            )
            since_checkpoint = [message]
            continue
        since_checkpoint.append(message)
        if isinstance(message, ModelRequest):
            user_parts = [p for p in message.parts if isinstance(p, UserPromptPart)]
            if user_parts:
                # A new user turn closes any open assistant turn.
                assistant = None
                part = user_parts[0]
                views.append(
                    MessageView(
                        role="user",
                        content=flatten_content(part.content),
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
