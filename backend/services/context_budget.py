"""Splitting the context footprint into the three things that fill it.

The provider tells us one number — how many tokens the last request cost — and nothing
about what they were spent on. Everything the operator can *act* on lives in the split:
a window that is 90% messages wants a compaction or a fresh thread, one that is 60% tool
schemas wants fewer tools switched on, and the two look identical from the total alone.

So the split is measured on our side, the same way the timings are, and for the same
reason: it has to mean the same thing on Anthropic, on an OpenAI-compatible endpoint, and
on a local server. No provider reports it, so nothing here can come from one.

**It is an estimate anchored to a fact.** The three parts are sized with the coarse
`CHARS_PER_TOKEN` proxy the rest of the codebase already uses for soft budgets, and then
scaled so they sum to exactly the token count the provider reported. The total is
therefore always right and the split is approximately right — which is the honest shape of
the thing, and why every figure the UI renders from this carries a `~`. Scaling also
absorbs what the proxy can't see (per-message framing, special tokens, a tokenizer that
isn't four-chars-a-token) by spreading it across the parts in proportion, rather than
letting it pile up in whichever part happens to be measured last.
"""

from __future__ import annotations

from typing import Any

from runs import ContextComposition, TurnOverhead

from .conversation_view import message_chars

#: Characters per token, by content kind — measured against cl100k on representative
#: samples and pinned by a calibration test.
#:
#: There are two of these rather than the one `core.text.CHARS_PER_TOKEN` because this is
#: a **split**, and a split is only as good as the *relative* accuracy of its parts. JSON
#: spends about a third of its characters on punctuation and short repeated keys, so it
#: tokenizes denser than prose; dividing both by the same 4 leaves the prose parts — the
#: standing brief, the conversation text — inflated by roughly a fifth against the JSON
#: ones, which on a tool-heavy thread is the difference between "your tools are the
#: problem" and "your conversation is". Absolute accuracy matters much less: the parts are
#: scaled to the provider's own total afterwards, so a bias shared by all three cancels
#: and only the difference between them survives.
#:
#: Code sits between the two (~4.3) and is counted as prose, since it arrives as a string.
#: That over-credits a thread of pasted source by around a tenth, which is inside the
#: tolerance a `~` readout claims and well short of the error a shared divisor produces.
CHARS_PER_TOKEN_PROSE = 4.8
CHARS_PER_TOKEN_JSON = 4.1


def compose(
    used: int | None, overhead: TurnOverhead | None, messages: list[Any]
) -> ContextComposition | None:
    """Split ``used`` — the provider's own footprint figure — three ways.

    Returns None when there is nothing to split (no measured footprint) or nothing to
    split it *with* (no overhead was captured, which is the case for a turn that never
    reached a model request). Absent rather than guessed: a composition with a zeroed
    system and tools would read as "this thread carries no overhead", which is never true
    and is exactly the sort of flattering zero the readout's absent-not-zero rule exists
    to keep off the screen."""
    if not used or overhead is None:
        return None
    # Each part converted at its own rate — the brief is prose, the schemas are JSON, and
    # the conversation is both — before any of them are compared.
    body = message_chars(messages)
    parts = (
        overhead.system / CHARS_PER_TOKEN_PROSE,
        overhead.tools / CHARS_PER_TOKEN_JSON,
        body.prose / CHARS_PER_TOKEN_PROSE + body.structured / CHARS_PER_TOKEN_JSON,
    )
    total = sum(parts)
    if total <= 0:
        return None
    scaled = [round(part / total * used) for part in parts]
    # Rounding three shares independently can miss the total by a token or two, and a
    # breakdown that doesn't add up to the figure printed above it looks like a bug even
    # when the drift is 1. The largest part absorbs it, being the one where a token is
    # least visible.
    biggest = scaled.index(max(scaled))
    scaled[biggest] += used - sum(scaled)
    return ContextComposition(system=scaled[0], tools=scaled[1], messages=scaled[2])


class OverheadCache:
    """The last overhead measured, per conversation mode.

    **Why this is remembered rather than stored.** A cold load has no request to measure —
    the tool schemas and the standing brief never reach the message history — so without
    something here, opening an existing thread would show no split until the operator sent
    another message, which is exactly when they least want to (the reason to look is to
    decide whether to send one at all).

    The obvious fix, writing the figures onto the conversation the way the timings are
    written, is the wrong one. Timings are history: what that turn cost is true forever.
    Overhead is *configuration* — which tools are switched on, what the brief says — and it
    describes what the **next** turn will cost. Persisting it would mean a thread opened
    after the operator switched half their tools off would confidently report the old tool
    weight, and a readout that is confidently wrong is worse than one that is absent.

    Keyed by mode because that is what changes the answer: a coding thread and a chat
    thread are handed different tools. Process-local and rebuildable — it refills on the
    first turn after a restart, and until then the split is simply absent."""

    def __init__(self) -> None:
        self._by_mode: dict[str, TurnOverhead] = {}

    def remember(self, mode: str, overhead: TurnOverhead | None) -> None:
        """Record what a turn in ``mode`` just measured. A failed measurement is ignored
        rather than stored as absence: the previous good figure still describes the
        configuration better than nothing does."""
        if overhead is not None:
            self._by_mode[mode] = overhead

    def get(self, mode: str) -> TurnOverhead | None:
        return self._by_mode.get(mode)
