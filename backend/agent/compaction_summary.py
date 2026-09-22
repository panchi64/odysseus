"""The summary itself — how it is produced from transcript chunks, and how the text that
comes back is handled.

**Producing it is a map/reduce**, because the stretch being folded is by definition most of
the *main* model's window and the utility model's is often smaller. Rather than eliding the
middle of the thread — which is usually where the work was — the transcript is split at
turn boundaries into pieces that fit (``agent.compaction_transcript``), each is summarized,
and the partial summaries are merged into one. Every call in a fold runs against a single
shared deadline, so a chunked fold cannot outlast the budget the run allowed for it, and
every call's output is stripped of a leaked ``<think>`` block before it can become the
thread's standing memory.

**Handling what comes back is text-only.** The summary is asked for in fixed sections
(``prompts/utility.py``'s ``COMPACT_INSTRUCTIONS``) for two reasons that need the text to
be *parseable*, not merely readable:

- **Anchors survive every fold.** Exact paths, ids, names and numbers are what a
  re-summarized summary loses first — each pass paraphrases a little more until the file
  path the thread was working on is "the config file". So a second fold carries the
  previous checkpoint's Anchors section forward **verbatim** instead of asking a model to
  restate it.
- **Tool-sourced facts stay marked as data.** The checkpoint is replayed as a
  user-shaped message, which is the most authoritative voice in the history; the one
  section that repeats what a web page or a document said is fenced before it is stored,
  so a fold cannot promote fetched text into an instruction the model trusts.

Both operations are text-in/text-out and model-free: a summary that comes back without the
headings degrades to "no carry-forward, nothing fenced" rather than failing the fold.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from pydantic_ai import ModelMessage, ModelRequest, UserPromptPart
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings

from core.compaction_sections import (
    replace_section,
    section_body,
    section_key,
    without_fenced,
)
from core.text import strip_think_blocks
from core.untrusted import new_nonce, untrusted_fence, untrusted_preamble
from prompts.utility import (
    COMPACT_ANCHORS_SECTION,
    COMPACT_INSTRUCTIONS,
    COMPACT_MARKER,
    COMPACT_REDUCE_INSTRUCTIONS,
    COMPACT_TOOLS_SECTION,
)
from services.conversation_view import flatten_content

from .meta import make_utility_agent

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SummaryDelta:
    """A piece of the summary as the model writes it, with where it sits in the fold.

    ``part``/``parts`` exist because a chunked fold is several model calls and a client
    rendering one stream of text would otherwise show the summary restarting from the top
    two or three times with no explanation. ``parts`` counts the **merge** as well as the
    chunks (``len(chunks) + 1``), since it is a pass the operator waits through like any
    other; a single-chunk fold — the common one — is simply ``1 of 1``."""

    text: str
    part: int
    parts: int


#: Where a fold's summary text goes while it is being written. Synchronous and
#: fire-and-forget: it is a progress signal, so it must not be able to fail a fold or slow
#: the model call down, and the caller that supplies one is the caller that owns a stream.
type DeltaSink = Callable[[SummaryDelta], None]

#: What a *single call* hands its text to — bare strings, with no idea which pass it is.
#: Separate from :data:`DeltaSink` because only the layer that knows how many passes there
#: are can say which one this is, and a single type for both would let a call site pass a
#: raw string where a stamped delta is expected.
type TextSink = Callable[[str], None]


async def summarize_chunks(
    model: Model,
    chunks: list[str],
    *,
    settings: ModelSettings,
    timeout_s: float | None,
    on_delta: DeltaSink | None = None,
) -> str | None:
    """One summary out of one or many transcript chunks, or ``None`` on any failure.

    The single-chunk case — the common one — is exactly the one call compaction always
    made. More chunks map to one summary each and then reduce to a single briefing; a
    failure anywhere gives up the whole fold, because half a memory stored as the thread's
    memory is worse than no compaction.

    ``on_delta`` is stamped with the pass it came from on the way past, so a client can say
    which of several it is watching rather than showing the summary appear to restart."""
    deadline = _Deadline(timeout_s)

    def sink(part: int, parts: int) -> TextSink | None:
        """This pass's text sink — the caller's delta sink with the pass stamped onto it."""
        if (emit := on_delta) is None:
            return None
        return lambda text: emit(SummaryDelta(text=text, part=part, parts=parts))

    if len(chunks) == 1:
        return await _run(model, COMPACT_INSTRUCTIONS, chunks[0], settings, deadline, sink(1, 1))
    # The merge is a pass of its own and the operator waits through it, so it is counted.
    total = len(chunks) + 1
    parts: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        prompt = f"Part {index} of {len(chunks)} of the earlier conversation.\n\n{chunk}"
        part = await _run(
            model, COMPACT_INSTRUCTIONS, prompt, settings, deadline, sink(index, total)
        )
        if part is None:
            return None
        parts.append(f"--- Part {index} of {len(chunks)} ---\n{part}")
    return await _run(
        model,
        COMPACT_REDUCE_INSTRUCTIONS,
        "\n\n".join(parts),
        settings,
        deadline,
        sink(total, total),
    )


class _Deadline:
    """The wall clock a whole fold runs against.

    A chunked fold makes several model calls, and giving each of them the caller's full
    timeout would let one compaction run for a multiple of the budget the run allowed —
    long enough for the inactivity watchdog to fire on a turn that was only making room for
    itself. One deadline, shared by every call."""

    def __init__(self, timeout_s: float | None) -> None:
        self._timeout_s = timeout_s
        self._started = time.monotonic()

    def remaining(self) -> float | None:
        """Seconds left, or ``None`` when the caller set no timeout."""
        if self._timeout_s is None:
            return None
        return self._timeout_s - (time.monotonic() - self._started)


async def _run(
    model: Model,
    instructions: str,
    prompt: str,
    settings: ModelSettings,
    deadline: _Deadline,
    on_delta: TextSink | None = None,
) -> str | None:
    """One summarizer call, bounded by the fold's shared deadline.

    ``on_delta`` receives the output as it arrives. **The deltas are handed over raw** —
    unstripped, unparsed, not yet merged with carried anchors and not yet fenced — because
    they are for a human watching a pause go by, and the alternative is showing them
    nothing until the whole call lands. Everything that makes the text *safe to store* is
    done to the settled string below and never to a delta: a fence cannot be applied to
    half a section, and a ``<think>`` block cannot be recognised until it closes.

    So a client rendering these is rendering the model's working, not the checkpoint. The
    checkpoint is what ``conversation.compacted`` carries, and that one has been through
    all of it."""
    remaining = deadline.remaining()
    if remaining is not None and remaining <= 0:
        logger.warning("conversation compaction summary failed: the fold ran out of time")
        return None
    agent = make_utility_agent(model, output_type=str, instructions=instructions)
    try:
        # `asyncio.timeout` rather than `wait_for`, because the streaming arm is an async
        # context manager rather than an awaitable. Both arms are inside it, so the shared
        # deadline bounds a stalled stream exactly as it bounds a slow single call.
        # TimeoutError is an Exception subclass (caught below); CancelledError is not, so a
        # cancelled run still propagates rather than degrading to "no summary".
        async with asyncio.timeout(remaining):
            if on_delta is None:
                output = (await agent.run(prompt, model_settings=settings)).output
            else:
                async with agent.run_stream(prompt, model_settings=settings) as stream:
                    async for delta in stream.stream_text(delta=True):
                        on_delta(delta)
                    output = await stream.get_output()
    except Exception as exc:  # noqa: BLE001 — compaction is best-effort, never fails a turn
        logger.warning("conversation compaction summary failed: %s", exc)
        return None
    # Reasoning was requested off, but the lever is best-effort: a runtime that ignores it
    # inlines the chain-of-thought as a `<think>…</think>` block in the content. Left in,
    # that block *becomes* the thread's memory — the model would replay the summarizer's
    # scratch reasoning as established fact for the rest of the conversation. Same call the
    # namer makes, and it handles the unclosed block a truncated think emits.
    return strip_think_blocks(output).strip() or None


def fence_tool_facts(summary: str) -> str:
    """Wrap the "From tools and documents" section's body in an untrusted fence.

    A no-op when the summarizer didn't emit that section (or emitted it empty) — the rest
    of the summary is the operator's and the assistant's own words, which are exactly what
    the checkpoint is supposed to speak with."""
    body = section_body(summary, COMPACT_TOOLS_SECTION)
    if not body:
        return summary
    nonce = new_nonce()
    fenced = f"{untrusted_preamble(nonce)}\n{untrusted_fence(body, nonce, source='tools')}"
    return replace_section(summary, COMPACT_TOOLS_SECTION, fenced)


def carried_anchors(messages: list[ModelMessage]) -> list[str]:
    """The Anchors lines of any checkpoint among the messages being folded.

    A fold's input contains the previous checkpoint whenever the thread has compacted
    before; it is recognised by the label the store wrote in front of it, the same marker
    the reviewer and the operator's transcript key on."""
    lines: list[str] = []
    for text in _checkpoint_texts(messages):
        lines.extend(_bullets(section_body(text, COMPACT_ANCHORS_SECTION)))
    return _dedupe(lines)


def merge_anchors(summary: str, carried: list[str]) -> str:
    """Fold ``carried`` anchor lines into the summary's Anchors section, keeping the new
    ones first and dropping duplicates. Appends the section when the summary has none."""
    if not carried:
        return summary
    existing = _bullets(section_body(summary, COMPACT_ANCHORS_SECTION))
    merged = _dedupe(existing + carried)
    if merged == existing:
        return summary
    body = "\n".join(merged)
    if section_body(summary, COMPACT_ANCHORS_SECTION) is None:
        return f"{summary.rstrip()}\n\n## {COMPACT_ANCHORS_SECTION}\n{body}"
    return replace_section(summary, COMPACT_ANCHORS_SECTION, body)


def _bullets(body: str | None) -> list[str]:
    """A section's non-empty lines, as written."""
    if not body:
        return []
    return [line.rstrip() for line in body.splitlines() if line.strip()]


def _dedupe(lines: list[str]) -> list[str]:
    """Order-preserving dedupe, comparing on the line's words rather than its bullet
    marker or spacing — the same anchor rewritten as "- x" and "* x" is one anchor."""
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        key = section_key(line)
        if key and key not in seen:
            seen.add(key)
            out.append(line)
    return out


def _checkpoint_texts(messages: list[ModelMessage]) -> list[str]:
    """The stored checkpoint texts among a fold's messages, newest last — **with every
    fenced region removed**, so what is carried forward is only what the summarizer wrote
    in its own voice."""
    texts: list[str] = []
    for message in messages:
        if not isinstance(message, ModelRequest):
            continue
        for part in message.parts:
            if isinstance(part, UserPromptPart):
                text = flatten_content(part.content).strip()
                if text.startswith(COMPACT_MARKER):
                    texts.append(without_fenced(text))
    return texts


