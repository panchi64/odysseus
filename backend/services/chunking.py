"""Pure token-window chunking — slice a document into overlapping passages.

A long document must be split before embedding: one vector per file is too coarse
to retrieve a relevant passage. This is the small, pure step that does it — a
sliding window of whitespace tokens with a fixed overlap, so a passage that
straddles a window boundary still lands wholly inside an adjacent chunk.

Deliberately dependency-free (whitespace tokens, not a model tokenizer): it runs
off the DB/embedder hot path and stays portable. Each chunk reports the character
offset it began at in the source text, so a hit can point back to its origin
(``<path>#<offset>``).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Chunk:
    """One passage: its text and the character offset it began at in the source."""

    text: str
    offset: int
    ordinal: int


def chunk_text(text: str, *, window: int = 512, overlap: int = 64) -> list[Chunk]:
    """Split ``text`` into overlapping ``window``-token passages.

    Tokens are whitespace-delimited; consecutive windows share ``overlap`` tokens
    so a passage spanning a boundary is wholly contained in one of them. Short text
    (≤ ``window`` tokens) yields a single chunk; empty/whitespace-only text yields
    none. ``offset`` is the character index where each chunk's first token begins.
    """
    if overlap >= window:
        raise ValueError("overlap must be smaller than window")
    # (token, char-offset) pairs — the offset lets a chunk point back into the source.
    spans: list[tuple[str, int]] = []
    cursor = 0
    for raw in text.split():
        start = text.index(raw, cursor)
        spans.append((raw, start))
        cursor = start + len(raw)
    if not spans:
        return []

    step = window - overlap
    chunks: list[Chunk] = []
    ordinal = 0
    for start in range(0, len(spans), step):
        window_spans = spans[start : start + window]
        if not window_spans:
            break
        offset = window_spans[0][1]
        passage = " ".join(token for token, _off in window_spans)
        chunks.append(Chunk(text=passage, offset=offset, ordinal=ordinal))
        ordinal += 1
        if start + window >= len(spans):
            break  # the last window reached the end — no trailing partial to add
    return chunks
