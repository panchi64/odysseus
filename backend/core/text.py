"""Tiny text/token utilities shared across layers.

There is no exact tokenizer at the points these are used (conversation compaction's
footprint estimate, the summarizer's input budget), and the budgets they serve are *soft*,
so a coarse characters-per-token proxy is good enough to bound sizes deterministically.
Kept here, in the foundation layer, so every caller shares one estimate, not several.

:func:`replace_unique` is here for the same reason: surgical editing is the shape of both
``DOC-2`` and ``SKILL-3``, and one implementation of "replace exactly one span or refuse"
means both surfaces refuse identically. So is :func:`strip_think_blocks` — every utility
model call that asks for reasoning off has to survive a runtime that ignores the lever.
"""

from __future__ import annotations

import re

from .exceptions import SpanEditError

# A coarse characters≈tokens proxy. Good enough for soft budgets; not a real tokenizer.
CHARS_PER_TOKEN = 4

# A reasoning model that the runtime didn't keep off inlines its chain-of-thought as a
# ``<think>…</think>`` block in the *content* (rather than a separate reasoning channel
# Pydantic AI would surface as a ``ThinkingPart``). The close is optional (``$`` under
# DOTALL): a model that exhausts ``max_tokens`` while still reasoning emits an *unclosed*
# ``<think>`` whose partial content Pydantic AI still returns — strip that to end-of-string
# so a half-thought can never be mistaken for the answer. Case-insensitive, since the tag
# casing is the model/template's choice, not ours.
_THINK_BLOCK = re.compile(r"<think>.*?(?:</think>|$)", re.DOTALL | re.IGNORECASE)


def strip_think_blocks(text: str) -> str:
    """Drop any inlined ``<think>…</think>`` reasoning from a model's text output.

    The reasoning-off lever is **best-effort, not guaranteed** — LM Studio drops OpenAI
    ``chat_template_kwargs``, the Qwen 2507+ line dropped the ``/no_think`` soft-switch —
    so every utility call that asks for reasoning off (the conversation namer, the
    compaction summarizer) has to be able to read past a think block it didn't want. One
    implementation, so a runtime that leaks reasoning leaks it into no surface at all.
    No-op when there's no think block."""
    return _THINK_BLOCK.sub("", text)


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
