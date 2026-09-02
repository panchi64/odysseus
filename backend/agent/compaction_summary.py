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
import re
import time

from pydantic_ai import ModelMessage, ModelRequest, UserPromptPart
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings

from core.text import strip_think_blocks
from core.untrusted import new_nonce, untrusted_fence, untrusted_preamble
from prompts.utility import (
    COMPACT_ANCHORS_SECTION,
    COMPACT_INSTRUCTIONS,
    COMPACT_MARKER,
    COMPACT_REDUCE_INSTRUCTIONS,
    COMPACT_SECTIONS,
    COMPACT_TOOLS_SECTION,
)
from services.conversation_view import flatten_content

from .meta import make_utility_agent

logger = logging.getLogger(__name__)


async def summarize_chunks(
    model: Model, chunks: list[str], *, settings: ModelSettings, timeout_s: float | None
) -> str | None:
    """One summary out of one or many transcript chunks, or ``None`` on any failure.

    The single-chunk case — the common one — is exactly the one call compaction always
    made. More chunks map to one summary each and then reduce to a single briefing; a
    failure anywhere gives up the whole fold, because half a memory stored as the thread's
    memory is worse than no compaction."""
    deadline = _Deadline(timeout_s)
    if len(chunks) == 1:
        return await _run(model, COMPACT_INSTRUCTIONS, chunks[0], settings, deadline)
    parts: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        prompt = f"Part {index} of {len(chunks)} of the earlier conversation.\n\n{chunk}"
        part = await _run(model, COMPACT_INSTRUCTIONS, prompt, settings, deadline)
        if part is None:
            return None
        parts.append(f"--- Part {index} of {len(chunks)} ---\n{part}")
    return await _run(model, COMPACT_REDUCE_INSTRUCTIONS, "\n\n".join(parts), settings, deadline)


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
    model: Model, instructions: str, prompt: str, settings: ModelSettings, deadline: _Deadline
) -> str | None:
    """One summarizer call, bounded by the fold's shared deadline."""
    remaining = deadline.remaining()
    if remaining is not None and remaining <= 0:
        logger.warning("conversation compaction summary failed: the fold ran out of time")
        return None
    agent = make_utility_agent(model, output_type=str, instructions=instructions)
    try:
        run = agent.run(prompt, model_settings=settings)
        # asyncio.TimeoutError is an Exception subclass (caught below); CancelledError is
        # not, so a cancelled run still propagates rather than degrading to "no summary".
        result = await (asyncio.wait_for(run, remaining) if remaining is not None else run)
    except Exception as exc:  # noqa: BLE001 — compaction is best-effort, never fails a turn
        logger.warning("conversation compaction summary failed: %s", exc)
        return None
    # Reasoning was requested off, but the lever is best-effort: a runtime that ignores it
    # inlines the chain-of-thought as a `<think>…</think>` block in the content. Left in,
    # that block *becomes* the thread's memory — the model would replay the summarizer's
    # scratch reasoning as established fact for the rest of the conversation. Same call the
    # namer makes, and it handles the unclosed block a truncated think emits.
    return strip_think_blocks(result.output).strip() or None


# Sections are asked for as `## Name` lines; anything else in the text is body. A model
# that reaches for bold instead of hashes, or repeats the heading's gloss after the name,
# is still writing the section we asked for — so the pattern accepts both and the name is
# matched by prefix. Nothing here fails loudly: a summary whose headings don't parse simply
# gets no carry-forward and no fence, which is what the previous format got.
_HEADING = re.compile(
    r"^[ \t]*(?:#{1,3}|\*\*)[ \t]*(?P<name>[^\n#*]+?)[ \t]*\**[ \t]*:?[ \t]*$", re.MULTILINE
)

# …but only a heading naming one of *our* sections ends a section. The summarizer is asked
# to quote its sources verbatim, so a fetched page's own `## Notes for the assistant` (or a
# bolded tool name opening a list) arrives inside the summary looking exactly like a
# heading. Treating it as one would close the untrusted fence early and leave whatever
# followed it stored as the workspace's own voice — the injection this fence exists to
# stop. Anything not on the roster is body text, wherever it appears.
_SECTION_KEYS = tuple(re.sub(r"[^a-z0-9]+", " ", name.lower()).strip() for name in COMPACT_SECTIONS)

# A fence marker, either end. Used to strip a previous checkpoint's quoted tool content
# before its Anchors section is read: the summary that carried it may have omitted its own
# Anchors heading (the prompt allows omission), and then the first `## Anchors` in the text
# is one the fenced page wrote — lifting *those* lines forward would launder an injection
# into every later checkpoint, verbatim, forever.
_FENCE_MARKER = re.compile(r"\[(?:BEGIN|END) UNTRUSTED CONTENT\b[^\]]*\]")


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


def section_body(text: str, name: str) -> str | None:
    """The body under the ``## name`` heading, or ``None`` when there is no such heading."""
    span = _span(text, name)
    if span is None:
        return None
    start, end = span
    return text[start:end].strip()


def replace_section(text: str, name: str, body: str) -> str:
    """``text`` with the named section's body replaced. Returns it unchanged when the
    heading isn't there — the caller's job is to notice, not this one's."""
    span = _span(text, name)
    if span is None:
        return text
    start, end = span
    return "\n".join([text[:start].rstrip("\n"), body, text[end:].lstrip("\n")]).rstrip()


def _span(text: str, name: str) -> tuple[int, int] | None:
    """Where the named section's body starts and ends, matching the heading loosely (case,
    punctuation and any restated gloss are the model's choice, the section is ours).

    The section runs to the next heading **we asked for**, or to the end of the text — see
    ``_SECTION_KEYS``: a heading-shaped line the summarizer copied out of a tool result is
    part of that result, not the start of a new section."""
    wanted = _key(name)
    matches = [m for m in _HEADING.finditer(text) if _known_key(m.group("name")) is not None]
    for index, match in enumerate(matches):
        if not _key(match.group("name")).startswith(wanted):
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        return start, end
    return None


def _known_key(name: str) -> str | None:
    """The section this heading names, or ``None`` when it names none of ours."""
    key = _key(name)
    return next((section for section in _SECTION_KEYS if key.startswith(section)), None)


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


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
        key = _key(line)
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
                    texts.append(_without_fenced(text))
    return texts


def _without_fenced(text: str) -> str:
    """``text`` with everything between (and including) the untrusted-content markers
    dropped, an unclosed fence taking the rest of the text with it.

    A checkpoint is replayed as a user-shaped message — the most authoritative voice in the
    history — and its fenced section is the one part that repeats what a web page said. The
    carry-forward copies lines **verbatim** into the next checkpoint, outside any fence, so
    it must never be able to read a line out of one. Erring long is deliberate: dropping a
    genuine anchor costs a paraphrase, promoting a fetched instruction costs the fence."""
    out: list[str] = []
    fenced = False
    for line in text.splitlines():
        marker = _FENCE_MARKER.search(line)
        if marker is not None:
            fenced = marker.group().startswith("[BEGIN")
            continue
        if not fenced:
            out.append(line)
    return "\n".join(out)
