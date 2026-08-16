"""Tool-result compaction — the model ingests a digest, the operator keeps the full output.

A Pydantic AI history processor (installed as a ``ProcessHistory`` capability) that shrinks
what the model re-reads each turn: a large tool result from a *prior* turn is replaced with a
short notice — its size plus the one call (``expand_tool_result``) that brings it back verbatim.
No excerpt is kept: the model sees the placeholder, not a truncated slice of the output.

Two facts from Phase 0 (`tests/test_compaction.py`) fix the shape:

- A history processor is **not** persistence-transparent — its output *is*
  ``result.all_messages()``, which the engine persists. So we cannot compact freely and rely
  on the original surviving.
- The engine persists only ``messages[start:]`` — the **current** turn. Prior turns are
  already stored full and never re-recorded. So compaction is operator-lossless **iff it only
  ever touches prior turns** and leaves the current turn whole. The current turn — what gets
  persisted and what the operator is actively watching — stays full; prior-turn compaction is
  ephemeral (model-only), re-derived from the full DB history every turn.

The boundary between "prior" and "current" is **not guessed** from the messages: the engine
threads in the persistence index as ``CompactionContext.protect_from`` (everything at index
``>= protect_from`` is the current/persisted turn). Deriving it from the last ``UserPromptPart``
would be wrong — the verifier's corrective re-attempt injects a *second* user prompt mid-turn,
which would push the original attempt's tool returns onto the "prior" side and persist them as
unrecoverable digests. Anchoring to the persistence index keeps the protected set and the
persisted set identical.

No context-window/budget math: the trigger is a recency window with hysteresis (keep between K
and 2K−1 of the most recent *prior-turn* results full, digesting in K-sized batches so the
already-digested region stays byte-stable across turns — see ``_recent_full_ids``) plus a size
floor (don't bother digesting small results).
Hitting the real context ceiling is a separate, explicit stop — never a job compaction silently
absorbs.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.messages import ModelMessage, ToolReturnPart

from core.config import Settings
from core.text import tokens_to_chars
from tools import CompactionContext, RunDeps

# The rehydration tool as the model sees it — the `builtin` category's `expand_tool_result`,
# namespaced by the toolset stack (`category_tool`). Used in the notice pointer so the name is
# callable verbatim. The expand tool's own output is *not* exempt from later compaction: once a
# recently-expanded result ages past the rolling window it condenses again, so repeated expands
# can't grow the history without bound — the model just expands again if it still needs it.
EXPAND_TOOL = "builtin_expand_tool_result"

# The shortest result worth compacting when the operator sets no floor: a notice replaces the
# output, so the source must clear the notice's own length for compaction to actually save bytes.
_MIN_COMPACT_CHARS = 256


def build_compaction_context(
    settings: Settings,
    *,
    enabled: bool | None = None,
    keep_recent: int | None = None,
    min_tokens: int | None = None,
) -> CompactionContext:
    """Resolve the effective compaction config for a turn (operator defaults, with optional
    per-conversation overrides) into a fresh :class:`CompactionContext` (empty handle map).

    ``protect_from`` is left at its default (0 ⇒ nothing is "prior", a safe no-op); the engine
    sets it to the turn's persistence index once the conversation history is known."""
    return CompactionContext(
        enabled=settings.compaction_enabled if enabled is None else enabled,
        keep_recent=settings.compaction_keep_recent if keep_recent is None else keep_recent,
        min_tokens=settings.compaction_min_tokens if min_tokens is None else min_tokens,
    )


def compact_tool_returns(
    ctx: RunContext[RunDeps], messages: list[ModelMessage]
) -> list[ModelMessage]:
    """History processor: digest oversized tool results from prior turns for the model.

    Off (no context / disabled / nothing prior) ⇒ the history passes through untouched.
    Otherwise: messages before ``protect_from`` are prior turns; keep the K most-recent
    *prior-turn* results full, and replace older ones over the size floor with a notice + an
    ``expand_tool_result`` pointer, recording the full content for rehydration. The current turn
    (index ``>= protect_from``) is always left whole — it is exactly what the engine persists."""
    cc = ctx.deps.compaction
    if cc is None or not cc.enabled:
        return messages
    boundary = cc.protect_from
    if boundary <= 0:
        return messages  # nothing prior to compact

    # The rolling window counts *prior-turn* results only — the current turn is already
    # protected wholesale, so letting its returns consume the K budget would (in a turn that
    # itself makes >= K tool calls) digest every prior result at once.
    keep_full = _recent_full_ids(messages[:boundary], cc.keep_recent)
    floor = _min_compact_chars(cc.min_tokens)
    out: list[ModelMessage] = []
    for index, message in enumerate(messages):
        if index >= boundary:  # current turn — persistence-safe, leave whole
            out.append(message)
            continue
        new_parts = []
        changed = False
        for part in message.parts:
            size = _content_size(part.content) if isinstance(part, ToolReturnPart) else None
            if size is not None and size > floor and part.tool_call_id not in keep_full:
                cc.full_by_id[part.tool_call_id] = part.content
                new_parts.append(replace(part, content=_digest(size, part.tool_call_id)))
                changed = True
            else:
                new_parts.append(part)
        out.append(replace(message, parts=new_parts) if changed else message)
    return out


def _recent_full_ids(prior: list[ModelMessage], keep_recent: int) -> set[str]:
    """The tool_call_ids of the recent *prior-turn* tool results that stay full.

    The window has hysteresis: rather than keeping exactly the ``keep_recent`` newest
    (a boundary that would advance on every new result, rewriting a mid-history byte
    each turn and invalidating the inference engine's prefix cache from that point),
    the digest frontier advances in ``keep_recent``-sized jumps. A result stays full
    until a whole batch of newer ones has accumulated, then the batch digests at once —
    so between ``keep_recent`` and ``2×keep_recent − 1`` recent results are full at any
    time, and the already-digested region renders byte-identically for ~``keep_recent``
    consecutive turns."""
    if keep_recent <= 0:
        return set()
    ids = [
        part.tool_call_id
        for message in prior
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]
    excess = len(ids) - keep_recent
    if excess <= 0:
        return set(ids)
    frontier = (excess // keep_recent) * keep_recent
    return set(ids[frontier:])


def _content_size(content: Any) -> int | None:
    """The char-length of a tool result's content for compaction sizing, or ``None`` when it
    can't (or shouldn't) be compacted. A plain string is measured directly; a JSON-shaped
    structure (dict/list of scalars) by its serialized length. Binary/multimodal content
    (anything ``json.dumps`` rejects) returns ``None`` so it is handed back to the model
    verbatim — never replaced by a text notice."""
    if isinstance(content, str):
        return len(content)
    try:
        return len(json.dumps(content, ensure_ascii=False))
    except (TypeError, ValueError):
        return None


def _min_compact_chars(min_tokens: int) -> int:
    """A result must exceed this many characters to be worth compacting — the larger of the
    operator's floor and the notice's own size, so the digest is always smaller than its source."""
    return max(tokens_to_chars(min_tokens), _MIN_COMPACT_CHARS)


def _digest(size: int, tool_call_id: str) -> str:
    """The model-facing replacement for a compacted result: a notice stating the output was set
    aside (with its size) and the single call that brings it back verbatim — no excerpt kept."""
    return (
        f"[tool output compacted — {size} chars omitted; "
        f'call {EXPAND_TOOL}("{tool_call_id}") for the full output]'
    )
