"""Reshaping a message list before it is handed to a model, or to the store.

Four surgeries the chat engine performs on ``list[ModelMessage]``, none of which needs a
Run, a store, or anything else the orchestrators carry. They are here rather than inline
because each encodes a fact about how the library or a provider behaves — a dangling tool
call is a provider error, adjacent requests get merged at wire-prep — and those facts are
worth finding in one place when one of them changes.

Every one returns new objects. The store's in-memory tree hands out its messages by
reference, so mutating one in place would corrupt the durable history of every later read.
"""

from __future__ import annotations

from dataclasses import replace

from pydantic_ai import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)


def drop_dangling_tool_calls(messages: list[ModelMessage]) -> list[ModelMessage]:
    """Strip a trailing tool call that never received its result.

    A turn stopped at a bound (usage limit, loop guard, timeout) can leave history ending
    on a ``ModelResponse`` whose ``ToolCallPart`` has no matching ``ToolReturnPart`` — the
    call was requested but the bound tripped before it ran. Persisting that and replaying it
    on the next turn is a provider error (an assistant tool call with no following tool
    result → HTTP 400), which would break every later turn in the thread. Since this is the
    final message, any tool call in it is necessarily unanswered: drop those parts, and the
    whole message if nothing else remains."""
    if not messages or not isinstance(messages[-1], ModelResponse):
        return messages
    last = messages[-1]
    kept = [p for p in last.parts if not isinstance(p, ToolCallPart)]
    if len(kept) == len(last.parts):
        return messages
    if kept:
        return [*messages[:-1], replace(last, parts=kept)]
    return messages[:-1]


def with_tail_context(
    messages: list[ModelMessage], texts: list[str]
) -> list[ModelMessage]:
    """Append per-turn context to the trailing user request — the *model's view only*.

    The regenerate path re-runs a history that already ends in the user request, so
    there is no fresh ``user_prompt`` to carry the prompt-context providers' output;
    instead it rides on that trailing request here. Rebuilds via ``replace`` (never
    mutates — the store's in-memory tree shares these objects), and since the caller
    persists only ``messages[start:]``, a message replaced *before* ``start`` never
    reaches the durable history. No trailing user request (defensive) ⇒ unchanged."""
    if not messages or not isinstance(messages[-1], ModelRequest):
        return messages
    last = messages[-1]
    for index, part in enumerate(last.parts):
        if isinstance(part, UserPromptPart):
            content = part.content if isinstance(part.content, list) else [part.content]
            parts = list(last.parts)
            parts[index] = replace(part, content=[*content, *texts])
            return [*messages[:-1], replace(last, parts=parts)]
    return messages


def merge_consecutive_requests(messages: list[ModelMessage]) -> list[ModelMessage]:
    """Collapse adjacent ``ModelRequest``s the way Pydantic AI will anyway, **before**
    ``start`` is measured against the list.

    ``_finalize`` persists ``result.all_messages()[start:]`` with ``start`` the length of
    the history we handed in. That only holds while the library gives the history back at
    the length we supplied it — and it does not: preparing the wire format merges
    consecutive requests (most chat APIs cannot carry two user messages in a row), so
    ``all_messages()`` comes back *shorter* than what went in and ``start`` silently points
    one message too far, dropping the operator's own message from the turn it persists.

    Two things produce adjacent requests here, and both are load-bearing: a compaction
    checkpoint hoisted in front of a retained tail that opens on a user prompt, and
    :func:`split_injected_requests`' own output replayed on the *next* turn. Normalizing
    up front costs nothing (the library was going to do exactly this) and makes the index
    honest in both cases. New objects throughout — the store's in-memory tree shares these
    messages, so nothing here may mutate one in place.

    **Why not use the library's own boundary.** ``AgentRunResult.new_messages()`` slices at
    an index Pydantic AI maintains for exactly this hazard, and it is correct — for one
    agent run. Ours is not one agent run. A single operator-facing turn can span several:
    a continuation after the operator queued more text mid-answer, an approval resume, a
    verifier correction. Each re-enters with a rebuilt history, so the library's index
    marks the start of the *last* run's new messages, not of the turn — on a corrective
    re-attempt it points two messages into a turn that began at zero. On top of that, four
    of the five things measured against ``start`` (the timeout flush, the cancel flush, the
    error flush, the park) happen where no result exists to ask. So ``start`` stays ours,
    and this keeps it honest."""
    out: list[ModelMessage] = []
    for message in messages:
        if isinstance(message, ModelRequest) and out and isinstance(out[-1], ModelRequest):
            out[-1] = replace(out[-1], parts=[*out[-1].parts, *message.parts])
            continue
        out.append(message)
    return out


def split_injected_requests(messages: list[ModelMessage]) -> list[ModelMessage]:
    """Give each mid-run injected operator message its own persisted request.

    Mid-run steering appends ``UserPromptPart``s onto the tool-return request the
    model was about to receive (`_drive_turn`'s ``_inject_queued``). Persisting that
    merged request as-is would bury the operator's message inside a tool exchange —
    no tree node of its own, so no user bubble, no edit/regenerate anchor. Split it:
    the tool returns keep their request, and each injected part becomes its own
    ``ModelRequest`` right after. Replay stays wire-identical — the library re-merges
    consecutive requests (tool returns first) when preparing the model's input."""
    out: list[ModelMessage] = []
    for message in messages:
        if not isinstance(message, ModelRequest):
            out.append(message)
            continue
        user_parts = [p for p in message.parts if isinstance(p, UserPromptPart)]
        tool_parts = [p for p in message.parts if isinstance(p, ToolReturnPart | RetryPromptPart)]
        if not user_parts or not tool_parts:
            out.append(message)
            continue
        rest = [p for p in message.parts if not isinstance(p, UserPromptPart)]
        out.append(replace(message, parts=rest))
        out.extend(ModelRequest(parts=[part]) for part in user_parts)
    return out
