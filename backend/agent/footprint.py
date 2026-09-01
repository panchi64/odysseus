"""What a replay is about to *weigh* — the messages plus what rides beside them.

A thin seam over ``services.conversation_view.estimate_footprint``. The measurement layer
owns the estimator; the engine owns the decisions taken with it (when to fold, whether a
corrective re-attempt still fits, what the gauge says after a fold), and those decisions
must all read one number. Importing it through here is what makes that true — and, while
the measurement layer is still growing the function, gives the engine a definition with
the identical signature to build against.

The local definition is a fallback, not a second opinion: it is the same arithmetic the
measurement layer states, and it disappears the moment the import resolves.
"""

from __future__ import annotations

from typing import Any

from runs.overhead import TurnOverhead

try:  # the measurement layer owns this; the fallback below only covers its absence
    from services.conversation_view import estimate_footprint
except ImportError:  # pragma: no cover — exercised only before the estimator lands
    from services.conversation_view import estimate_tokens

    # Prose and serialized JSON do not tokenize at the same rate. The standing brief is
    # prose; the tool schemas are JSON. Measured against cl100k, roughly 4.8 and 4.1
    # characters per token.
    _PROSE_CHARS_PER_TOKEN = 4.8
    _STRUCTURED_CHARS_PER_TOKEN = 4.1

    def estimate_footprint(
        messages: list[Any],
        overhead: TurnOverhead | None,
        *,
        fallback_overhead_tokens: int,
    ) -> int:
        """The whole request's coarse size: the messages, plus the standing brief and the
        tool schemas that never reach the message history.

        ``fallback_overhead_tokens`` stands in when this thread has no measured overhead
        yet — a turn that has never completed, or one recorded before the measurement
        existed. Zero would be the wrong guess: the assembled catalog is worth thousands of
        tokens on every request, and a trigger that ignored it would fold far too late."""
        if overhead is None:
            extra = max(0, fallback_overhead_tokens)
        else:
            extra = int(
                overhead.system / _PROSE_CHARS_PER_TOKEN
                + overhead.tools / _STRUCTURED_CHARS_PER_TOKEN
            )
        return estimate_tokens(messages) + extra


#: What to assume a request's brief + tool schemas cost when this thread has never
#: measured them. The assembled catalog measures around 14k tokens, so zero is the one
#: answer that is certainly wrong; the config key is the operator-visible home for it and
#: this is the floor for a deployment that predates it.
_DEFAULT_OVERHEAD_FALLBACK_TOKENS = 12_000


def overhead_fallback_tokens(settings: Any) -> int:
    """The configured stand-in for an unmeasured brief + schemas, in tokens.

    Read through here rather than off ``settings`` directly so every caller of
    :func:`estimate_footprint` in the engine passes the same figure — a trigger and a
    gauge that disagreed about the overhead would disagree about fullness."""
    configured = getattr(
        settings, "context_overhead_fallback_tokens", _DEFAULT_OVERHEAD_FALLBACK_TOKENS
    )
    return int(configured)


__all__ = ["estimate_footprint", "overhead_fallback_tokens"]
