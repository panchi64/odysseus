"""The embedding capability — turn text into vectors for semantic recall.

A thin async interface over the configured ``embedding``-role endpoint (resolved
from the model registry). It calls the provider's OpenAI-compatible
``/embeddings`` API directly, since embeddings are not a Pydantic AI chat model.

Pluggable by design (the :class:`Embedder` protocol): the real implementation
talks to a model server; tests inject a deterministic fake. **Graceful
degradation (`XC-DEG-1`):** when no embedding endpoint is configured the embedder
is *unavailable* and raises :class:`~core.exceptions.DegradedCapabilityError`,
which the memory store catches to fall back to keyword recall (`MEM-2`).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np
from openai import AsyncOpenAI

from core.exceptions import DegradedCapabilityError
from core.vault import Vault
from services.registry import ModelRegistry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmbeddingBatch:
    """Vectors plus the provenance every stored vector records (`EMB-2`)."""

    vectors: list[list[float]]
    model: str
    dim: int


@runtime_checkable
class Embedder(Protocol):
    async def is_available(self, owner_id: str) -> bool: ...

    async def embed(self, owner_id: str, texts: list[str]) -> EmbeddingBatch: ...


class RegistryEmbedder:
    """Embeds via the operator's configured ``embedding``-role endpoint."""

    def __init__(self, registry: ModelRegistry) -> None:
        self._registry = registry

    async def is_available(self, owner_id: str) -> bool:
        try:
            await self._registry.resolve_embedding_spec(owner_id)
            return True
        except DegradedCapabilityError:
            return False

    async def embed(self, owner_id: str, texts: list[str]) -> EmbeddingBatch:
        # Raises DegradedCapabilityError when unconfigured — the caller degrades.
        spec = await self._registry.resolve_embedding_spec(owner_id)
        client = AsyncOpenAI(base_url=spec.base_url, api_key=spec.api_key or "not-needed")
        response = await client.embeddings.create(model=spec.model, input=texts)
        vectors = [item.embedding for item in response.data]
        dim = len(vectors[0]) if vectors else 0
        return EmbeddingBatch(vectors=vectors, model=spec.model, dim=dim)


async def embed_query(
    embedder: Embedder, owner_id: str, query: str
) -> tuple[np.ndarray | None, str | None]:
    """Embed a single query for hybrid recall, returning ``(vector, model)``.

    A degraded embedder (no endpoint, or a query that can't embed) yields
    ``(None, None)`` so the caller collapses to keyword-only — the `EMB-2`
    fallback shared by every recall path."""
    try:
        batch = await embedder.embed(owner_id, [query])
    except DegradedCapabilityError:
        return None, None
    except Exception:
        # A transient embedder failure (timeout, 5xx) is "semantic search
        # unavailable" too — degrade to keyword rather than failing the recall.
        logger.exception("query embedding failed; falling back to keyword recall")
        return None, None
    return np.asarray(batch.vectors[0], dtype=np.float64), batch.model


def decode_vector(vault: Vault, embedding_enc: str) -> list[float]:
    """Open a sealed embedding back into its float vector."""
    return json.loads(vault.decrypt_str(embedding_enc))
