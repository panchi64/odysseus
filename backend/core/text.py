"""Tiny text/token utilities shared across layers.

There is no exact tokenizer at the points these are used (persist-time attachment caps,
history compaction), and the budgets they serve are *soft*, so a coarse characters-per-token
proxy is good enough to bound sizes deterministically. Kept here, in the foundation layer, so
both the chat-attachments path and the compaction processor use one estimate, not two.
"""

from __future__ import annotations

# A coarse characters≈tokens proxy. Good enough for soft budgets; not a real tokenizer.
CHARS_PER_TOKEN = 4


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
