"""Embeddings that are deterministic, and unrelated texts that are actually unrelated.

Recall is ranked by cosine similarity, so a stub returning arbitrary vectors would give a
ranking that changes between runs and a fixture that asserts an order would be flaky for
reasons having nothing to do with the code. Hashing the text fixes the vector for a given
string forever, which makes an ordering assertion meaningful.

What hashing does *not* give is semantics: two texts about the same subject are as far
apart as two about different ones. That is the honest limit of this stub, and it is why
real retrieval quality is measured by the eval suite against a live embedder instead.
What this is for is the plumbing — that a document is chunked, embedded, stored, and
comes back — which is exactly what a visual check of the corpus surfaces needs.
"""

from __future__ import annotations

import hashlib
import math

#: Small enough to keep seeded rows cheap, large enough that unrelated texts are not
#: accidentally near each other.
DIMENSIONS = 256


def embed(text: str) -> list[float]:
    """A unit vector, fixed for this text and effectively unrelated to any other's."""
    # Two bytes per dimension, drawn from an extendable-output hash so the digest is as
    # long as the dimension count asks for rather than the other way round.
    raw = hashlib.shake_256(text.encode("utf-8")).digest(DIMENSIONS * 2)
    values = [
        int.from_bytes(raw[at : at + 2], "big") / 32767.5 - 1.0
        for at in range(0, DIMENSIONS * 2, 2)
    ]
    norm = math.sqrt(sum(value * value for value in values))
    # A zero norm needs 256 hash bytes to land exactly mid-range at once; the guard costs
    # a comparison and removes the one input that would return NaNs.
    return values if norm == 0 else [value / norm for value in values]
