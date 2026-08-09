"""Tiny text/token utilities shared across layers.

There is no exact tokenizer at the points these are used (persist-time attachment caps,
history compaction), and the budgets they serve are *soft*, so a coarse characters-per-token
proxy is good enough to bound sizes deterministically. Kept here, in the foundation layer, so
both the chat-attachments path and the compaction processor use one estimate, not two.

:func:`replace_unique` is here for the same reason: surgical editing is the shape of both
``DOC-2`` and ``SKILL-3``, and one implementation of "replace exactly one span or refuse"
means both surfaces refuse identically.
"""

from __future__ import annotations

from .exceptions import SpanEditError

# A coarse characters≈tokens proxy. Good enough for soft budgets; not a real tokenizer.
CHARS_PER_TOKEN = 4


def replace_unique(
    text: str, old: str, new: str, *, error: type[SpanEditError] = SpanEditError
) -> str:
    """Replace the **single** occurrence of ``old`` in ``text`` with ``new``.

    Raises ``error`` (a :class:`SpanEditError` subclass, carrying the occurrence count) when
    ``old`` is absent or matches more than once, so the caller can ask for a more precise
    span rather than guessing which match was meant. Callers run this inside their write
    transaction so the check and the replace are atomic."""
    occurrences = text.count(old)
    if occurrences != 1:
        raise error(occurrences)
    return text.replace(old, new, 1)


def tokens_to_chars(tokens: int) -> int:
    """The character budget for a token budget, floored at zero."""
    return max(0, tokens) * CHARS_PER_TOKEN


def truncate_on_boundary(text: str, max_chars: int) -> str:
    """The first ``max_chars`` of ``text``, trimmed back to a nearby whitespace boundary when
    one is reasonably close, so the cut doesn't split a word mid-token."""
    if max_chars <= 0 or len(text) <= max_chars:
        return text[:max_chars]
    cut = text[:max_chars]
    boundary = max(cut.rfind(" "), cut.rfind("\n"))
    if boundary > max_chars * 0.8:
        cut = cut[:boundary]
    return cut.rstrip()


def truncate_middle(text: str, max_chars: int) -> tuple[str, str, int]:
    """Cap ``text`` to ``max_chars`` by keeping a **head and a tail** and eliding the
    middle — the mirror image of :func:`truncate_on_boundary`, which keeps only the
    head. Useful when the interesting part could be either the setup (head) or the
    final state/error (tail, where a failing process's output usually lands).

    Returns ``(head, tail, elided_chars)``. When ``text`` already fits, ``head`` is
    the text unchanged, ``tail`` is empty, and ``elided_chars`` is 0 — the caller can
    always safely use ``head`` alone in that case, and insert its own marker between
    ``head``/``tail`` only when ``elided_chars`` is nonzero."""
    if max_chars <= 0 or len(text) <= max_chars:
        return text, "", 0
    head_len = max_chars // 2
    tail_len = max_chars - head_len
    head = text[:head_len]
    tail = text[len(text) - tail_len :] if tail_len else ""
    elided = len(text) - head_len - tail_len
    return head, tail, elided
