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

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from openai import AsyncOpenAI

from core.exceptions import DegradedCapabilityError
from services.registry import ModelRegistry


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
