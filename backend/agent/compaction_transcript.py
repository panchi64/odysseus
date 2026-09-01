"""Rendering a stretch of conversation for the compaction summarizer.

Split out of :mod:`agent.summarize` because the two answer different questions: that
module decides *when* a thread folds and records the result; this one decides *what the
summarizer is allowed to read*, which is where both the trust boundary and the input
budget live.

Two properties this file exists to hold:

- **Tool output stays fenced.** The summary the summarizer writes is stored as a
  user-shaped checkpoint the main model replays as its own memory, so a page the agent
  fetched could otherwise launder instructions into the thread's standing context by way
  of the summarizer. Every tool return and retry is therefore rendered inside an
  :func:`core.untrusted.untrusted_fence` sharing one per-fold nonce, announced once at the
  top; the operator's and the assistant's own lines stay outside it, because those are the
  two voices the summary is *supposed* to speak for.
- **Truncation never cuts a fence.** The per-result cap is applied to the payload
  *before* it is fenced, and the last-resort shrink drops whole rendered lines rather than
  slicing through a marker — an END marker that survived its BEGIN would leave untrusted
  text sitting outside the fence.

The budget is spent by **chunking, not eliding**: turns are packed into as many
summarizer-sized pieces as it takes (:func:`transcript_chunks`), and the caller maps over
them. Head-and-tail elision only happens inside a single turn too large to fit alone.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic_ai import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from core.serde import jsonable
from core.text import tokens_to_chars, truncate_middle
from core.untrusted import new_nonce, untrusted_fence, untrusted_preamble
from prompts.utility import COMPACT_MARKER
from services.conversation_view import flatten_content

# Per-entry cap on a rendered tool result, applied *inside* the fence. Generous, because
# what a tool returned is exactly the kind of detail a fold must not lose; a transcript
# that outgrows the summarizer's window is split into more chunks rather than cut shorter.
TOOL_RESULT_CHARS = 6000

# Below this, shrinking a single oversize turn stops paying: keep dropping caps and the
# remaining text says nothing. Whole lines go from the middle instead.
_MIN_RESULT_CHARS = 250


@dataclass(frozen=True)
class _Line:
    """One rendered transcript line. ``untrusted`` is the tool-sourced payload that must be
    fenced; ``label`` is the chassis' own words about it, which must not be."""

    label: str
    untrusted: str | None = None
    source: str | None = None


def render_transcript(messages: list[ModelMessage]) -> str:
    """The whole stretch as one labelled transcript — a single untrusted preamble, then the
    lines, with every tool return fenced under that preamble's nonce.

    No input budget: fitting the summarizer is :func:`transcript_chunks`' job, and a caller
    that wants the transcript whole (a test, a debug readout) wants it whole."""
    chunks = transcript_chunks(messages)
    return chunks[0] if chunks else ""


def transcript_chunks(
    messages: list[ModelMessage], *, max_input_tokens: int | None = None
) -> list[str]:
    """The transcript split at **turn boundaries** into pieces that each fit
    ``max_input_tokens``, or a single piece when it all fits (the common case) or no budget
    was given. Empty when there was nothing worth rendering.

    Splitting on turns rather than characters is what makes each piece summarizable on its
    own: a chunk that opened mid-tool-call would ask the summarizer to explain a result
    whose request it never saw."""
    nonce = new_nonce()
    preamble = untrusted_preamble(nonce)
    turns = [lines for lines in (_render_turn(turn) for turn in _split_turns(messages)) if lines]
    if not turns:
        return []
    if max_input_tokens is None:
        body = "\n\n".join(_join(_full(turn, nonce)) for turn in turns)
        return [f"{preamble}\n\n{body}"]
    budget = max(tokens_to_chars(max_input_tokens) - len(preamble) - 2, _MIN_RESULT_CHARS)
    return [f"{preamble}\n\n{body}" for body in _pack(turns, nonce, budget)]


def _pack(turns: list[list[_Line]], nonce: str, budget: int) -> list[str]:
    """Greedily fill chunks with whole turns, shrinking any single turn that can't fit one
    on its own."""
    chunks: list[str] = []
    current = ""
    for turn in turns:
        text = _join(_full(turn, nonce))
        if len(text) > budget:
            text = _shrink(turn, nonce, budget)
        if current and len(current) + 2 + len(text) > budget:
            chunks.append(current)
            current = text
        else:
            current = f"{current}\n\n{text}" if current else text
    if current:
        chunks.append(current)
    return chunks


def _full(turn: list[_Line], nonce: str) -> list[str]:
    """A turn's lines at full size — tool payloads capped at :data:`TOOL_RESULT_CHARS`,
    everything the operator and the assistant said left intact."""
    return [_render_line(line, nonce, TOOL_RESULT_CHARS, None) for line in turn]


def _shrink(turn: list[_Line], nonce: str, budget: int) -> str:
    """One oversize turn brought under ``budget``: halve the caps until it fits, then drop
    whole lines from the middle. Both steps keep every fence intact — the caps apply to the
    payload before it is wrapped, and dropping is line-granular."""
    cap = TOOL_RESULT_CHARS
    while cap > _MIN_RESULT_CHARS:
        cap //= 2
        lines = [_render_line(line, nonce, cap, max(cap, _MIN_RESULT_CHARS)) for line in turn]
        text = _join(lines)
        if len(text) <= budget:
            return text
    return _drop_middle(
        [_render_line(line, nonce, _MIN_RESULT_CHARS, _MIN_RESULT_CHARS) for line in turn], budget
    )


def _drop_middle(lines: list[str], budget: int) -> str:
    """Keep as many head and tail lines as ``budget`` allows and name what went.

    The last resort, and the only place a fold still loses content outright: one turn whose
    own rendering, already capped to the floor, still cannot fit the summarizer's window."""
    head: list[str] = []
    tail: list[str] = []
    left, right, used = 0, len(lines) - 1, 0
    while left <= right:
        from_head = len(head) <= len(tail)
        pick = lines[left] if from_head else lines[right]
        if used + len(pick) + 1 > budget:
            break
        if from_head:
            head.append(pick)
            left += 1
        else:
            tail.insert(0, pick)
            right -= 1
        used += len(pick) + 1
    omitted = right - left + 1
    middle = [f"[… {omitted} transcript lines omitted …]"] if omitted > 0 else []
    return _join(head + middle + tail)


def _join(lines: list[str]) -> str:
    return "\n".join(line for line in lines if line)


def _split_turns(messages: list[ModelMessage]) -> list[list[ModelMessage]]:
    """Group messages into turns, each opening on a request that carries an operator
    prompt. Anything before the first prompt (a hoisted checkpoint, a dangling return)
    rides with the turn that follows it."""
    turns: list[list[ModelMessage]] = []
    current: list[ModelMessage] = []
    started = False
    for message in messages:
        if _opens_turn(message):
            if started:
                turns.append(current)
                current = []
            started = True
        current.append(message)
    if current:
        turns.append(current)
    return turns


def _opens_turn(message: ModelMessage) -> bool:
    return isinstance(message, ModelRequest) and any(
        isinstance(part, UserPromptPart) for part in message.parts
    )


def _render_turn(messages: list[ModelMessage]) -> list[_Line]:
    lines: list[_Line] = []
    for message in messages:
        lines.extend(_render_message(message))
    return lines


def _render_message(message: ModelMessage) -> list[_Line]:
    """One message as labelled lines, or nothing when it carries nothing useful.

    Thinking parts are deliberately dropped: a model's scratch reasoning is the least
    durable thing in the history and the most expensive per token, and none of it is a fact
    the continuing thread needs. Tool calls and their results are kept — what the agent
    looked up, and what came back, is exactly the sort of detail that must survive a fold."""
    lines: list[_Line] = []
    if isinstance(message, ModelRequest):
        for part in message.parts:
            if isinstance(part, UserPromptPart):
                text = flatten_content(part.content).strip()
                if text:
                    # A checkpoint from an earlier fold is user-shaped but is not the
                    # operator; labelling it as one would have the summarizer attribute the
                    # workspace's own briefing to them.
                    label = "EARLIER SUMMARY" if text.startswith(COMPACT_MARKER) else "OPERATOR"
                    lines.append(_Line(f"{label}: {text}"))
            elif isinstance(part, ToolReturnPart):
                lines.append(
                    _Line(
                        f"TOOL {part.tool_name} returned:",
                        _payload(part.content),
                        part.tool_name,
                    )
                )
            elif isinstance(part, RetryPromptPart):
                lines.append(
                    _Line(
                        f"TOOL {part.tool_name} failed:",
                        part.model_response(),
                        part.tool_name,
                    )
                )
    elif isinstance(message, ModelResponse):
        for part in message.parts:
            if isinstance(part, TextPart):
                text = part.content.strip()
                if text:
                    lines.append(_Line(f"ASSISTANT: {text}"))
            elif isinstance(part, ToolCallPart):
                lines.append(_Line(f"ASSISTANT called {part.tool_name}({part.args_as_json_str()})"))
    return lines


def _render_line(line: _Line, nonce: str, result_chars: int, text_chars: int | None) -> str:
    """A line as transcript text: the label, plus — for a tool-sourced line — the payload
    capped and then fenced, in that order."""
    if line.untrusted is None:
        return line.label if text_chars is None else _cap(line.label, text_chars)
    fenced = untrusted_fence(_cap(line.untrusted, result_chars), nonce, source=line.source)
    return f"{line.label}\n{fenced}"


def _cap(text: str, max_chars: int) -> str:
    head, tail, elided = truncate_middle(text.strip(), max_chars)
    return head if not elided else f"{head}\n[… {elided} characters omitted …]\n{tail}"


def _payload(content: object) -> str:
    """A tool result as text — JSON-shaped results serialized, unserializable ones named."""
    if isinstance(content, str):
        return content
    try:
        return str(jsonable(content))
    except Exception:  # noqa: BLE001 — an unserializable result is still worth naming
        return f"<{type(content).__name__}>"
