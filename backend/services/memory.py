"""Long-term memory — store, recall by meaning, and manage memories.

The capability behind `MEM-*`. A memory is encrypted at rest (content + vector);
recall is **hybrid and brute-force**: at single-operator volumes we load the
owner's memories, decrypt them, and score each against the query two ways —

- **dense** (cosine over embeddings, the "by meaning" path), and
- **sparse** (token overlap, the keyword path) —

then fuse the two rankings with Reciprocal Rank Fusion. This satisfies `MEM-2`'s
"recall by meaning, keyword fallback" in one pass: when the embedding capability
is unavailable (or a memory has no vector), that item simply contributes via the
sparse signal alone. Pinned memories are always included (`MEM-4`).

Brute-force-in-Python (not an in-DB ANN index) is the deliberate consequence of
encrypting vectors at rest — see decision D18. It is microseconds at this scale
and keeps every vector sealed. The pluggable seam (a different store) stays open
for when volume, not confidentiality, becomes the constraint.

Embeddings are compared **only within the same model/space** (`EMB-2`): a memory
embedded by a different model than the current one falls back to sparse, so a
model change degrades recall rather than corrupting it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
from sqlalchemy import Engine
from sqlmodel import Session, select

from core.db import in_session
from core.exceptions import DegradedCapabilityError, NotFoundError
from core.vault import Vault
from models.memory import Memory
from services.embeddings import Embedder

_RRF_K = 60  # Reciprocal Rank Fusion constant (standard default)
_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN.findall(text.lower()))


@dataclass(frozen=True)
class MemoryView:
    """A decrypted memory for listing/editing (content in the clear to the owner)."""

    id: str
    content: str
    pinned: bool
    created_at: datetime
    updated_at: datetime
    has_embedding: bool


@dataclass(frozen=True)
class RecallHit:
    memory: MemoryView
    score: float
    # How it surfaced: semantic (dense only), keyword (sparse only), both, or pinned.
    matched_by: str


@dataclass(frozen=True)
class DuplicateGroup:
    """Near-duplicate memories an audit flags for consolidation (`MEM-3`)."""

    memory_ids: list[str]
    similarity: float


class MemoryStore:
    def __init__(self, engine: Engine, vault: Vault, embedder: Embedder) -> None:
        self._engine = engine
        self._vault = vault
        self._embedder = embedder

    # --- write path -------------------------------------------------------

    async def remember(self, owner_id: str, content: str, *, pinned: bool = False) -> MemoryView:
        model, dim, vector_enc = await self._embed_for_storage(owner_id, content)
        memory = Memory(
            owner_id=owner_id,
            content_enc=self._vault.encrypt_str(content),
            embedding_enc=vector_enc,
            embedding_model=model,
            embedding_dim=dim,
            pinned=pinned,
        )

        def work(session: Session) -> MemoryView:
            session.add(memory)
            session.flush()
            return self._to_view(memory, content)

        return await in_session(self._engine, work)

    async def update(
        self,
        owner_id: str,
        memory_id: str,
        *,
        content: str | None = None,
        pinned: bool | None = None,
    ) -> MemoryView:
        await self._require(owner_id, memory_id)
        # Re-embed only when the content actually changed (EMB-2 provenance).
        new_vector = (
            await self._embed_for_storage(owner_id, content) if content is not None else None
        )

        def work(session: Session) -> MemoryView:
            memory = session.get(Memory, memory_id)
            assert memory is not None
            if content is not None and new_vector is not None:
                memory.content_enc = self._vault.encrypt_str(content)
                memory.embedding_model, memory.embedding_dim, memory.embedding_enc = new_vector
            if pinned is not None:
                memory.pinned = pinned
            memory.updated_at = datetime.now(UTC)
            session.add(memory)
            session.flush()
            return self._to_view(memory, self._vault.decrypt_str(memory.content_enc))

        return await in_session(self._engine, work)

    async def delete(self, owner_id: str, memory_id: str) -> None:
        await self._require(owner_id, memory_id)

        def work(session: Session) -> None:
            memory = session.get(Memory, memory_id)
            if memory is not None:
                session.delete(memory)

        await in_session(self._engine, work)

    # --- read path --------------------------------------------------------

    async def list_memories(self, owner_id: str) -> list[MemoryView]:
        """The chronological timeline, newest first (`MEM-1`)."""
        def work(session: Session) -> list[MemoryView]:
            rows = session.exec(
                select(Memory)
                .where(Memory.owner_id == owner_id)
                .order_by(Memory.created_at.desc())  # type: ignore[attr-defined]
            ).all()
            return [self._to_view(row, self._vault.decrypt_str(row.content_enc)) for row in rows]

        return await in_session(self._engine, work)

    async def get(self, owner_id: str, memory_id: str) -> MemoryView:
        memory = await self._require(owner_id, memory_id)
        return self._to_view(memory, self._vault.decrypt_str(memory.content_enc))

    async def recall(self, owner_id: str, query: str, *, limit: int = 5) -> list[RecallHit]:
        """Hybrid recall: dense (meaning) + sparse (keyword), fused, plus pins.

        The query is embedded off the DB thread; scoring decrypts and ranks the
        working set on it. A degraded embedder (or a query that can't embed)
        collapses cleanly to keyword-only — the `MEM-2` fallback."""
        query_vec, query_model = await self._embed_query(owner_id, query)
        query_tokens = _tokens(query)

        def work(session: Session) -> list[RecallHit]:
            rows = session.exec(select(Memory).where(Memory.owner_id == owner_id)).all()
            decrypted = [(row, self._vault.decrypt_str(row.content_enc)) for row in rows]
            return self._rank(decrypted, query_vec, query_model, query_tokens, limit)

        return await in_session(self._engine, work)

    async def audit(self, owner_id: str, *, threshold: float = 0.92) -> list[DuplicateGroup]:
        """Flag near-duplicate memories for consolidation (`MEM-3`).

        Pairs whose embeddings exceed ``threshold`` cosine similarity are grouped.
        Detection only — the operator decides what to merge or delete."""
        def work(session: Session) -> list[DuplicateGroup]:
            rows = session.exec(select(Memory).where(Memory.owner_id == owner_id)).all()
            embedded = [
                (row.id, row.embedding_model, np.asarray(self._decode(row.embedding_enc)))
                for row in rows
                if row.embedding_enc is not None
            ]
            return self._duplicate_groups(embedded, threshold)

        return await in_session(self._engine, work)

    # --- internals --------------------------------------------------------

    async def _embed_query(self, owner_id: str, query: str) -> tuple[np.ndarray | None, str | None]:
        try:
            batch = await self._embedder.embed(owner_id, [query])
        except DegradedCapabilityError:
            return None, None  # keyword-only fallback (MEM-2)
        return np.asarray(batch.vectors[0], dtype=np.float64), batch.model

    async def _embed_for_storage(
        self, owner_id: str, content: str
    ) -> tuple[str | None, int | None, str | None]:
        """Embed content for storage, best-effort. Returns (model, dim, enc_vector);
        all-None when the embedder is unavailable (the memory is still stored, and
        recalls for it fall back to keyword)."""
        try:
            batch = await self._embedder.embed(owner_id, [content])
        except DegradedCapabilityError:
            return None, None, None
        vector = batch.vectors[0]
        return batch.model, batch.dim, self._vault.encrypt_str(json.dumps(vector))

    def _rank(
        self,
        decrypted: list[tuple[Memory, str]],
        query_vec: np.ndarray | None,
        query_model: str | None,
        query_tokens: set[str],
        limit: int,
    ) -> list[RecallHit]:
        dense: dict[str, float] = {}
        sparse: dict[str, float] = {}
        for memory, content in decrypted:
            overlap = len(query_tokens & _tokens(content))
            if overlap:
                sparse[memory.id] = float(overlap)
            # Dense only within the same embedding space (EMB-2), and only when
            # there's actual similarity — a zero/orthogonal vector is no signal.
            if (
                query_vec is not None
                and memory.embedding_enc is not None
                and memory.embedding_model == query_model
            ):
                score = _cosine(query_vec, np.asarray(self._decode(memory.embedding_enc)))
                if score > 0:
                    dense[memory.id] = score

        fused = _rrf(dense, sparse)
        views = {m.id: self._to_view(m, c) for m, c in decrypted}
        ranked = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:limit]

        hits = [
            RecallHit(memory=views[mid], score=score, matched_by=_matched_by(mid, dense, sparse))
            for mid, score in ranked
        ]
        # Pins are always included (MEM-4), appended if not already surfaced.
        present = {h.memory.id for h in hits}
        for memory, _content in decrypted:
            if memory.pinned and memory.id not in present:
                hits.append(RecallHit(memory=views[memory.id], score=0.0, matched_by="pinned"))
        return hits

    def _duplicate_groups(
        self, embedded: list[tuple[str, str | None, np.ndarray]], threshold: float
    ) -> list[DuplicateGroup]:
        groups: list[DuplicateGroup] = []
        used: set[str] = set()
        for i, (id_a, model_a, vec_a) in enumerate(embedded):
            if id_a in used:
                continue
            cluster = [id_a]
            best = 0.0
            for id_b, model_b, vec_b in embedded[i + 1 :]:
                if id_b in used or model_b != model_a:
                    continue
                sim = _cosine(vec_a, vec_b)
                if sim >= threshold:
                    cluster.append(id_b)
                    used.add(id_b)
                    best = max(best, sim)
            if len(cluster) > 1:
                used.add(id_a)
                groups.append(DuplicateGroup(memory_ids=cluster, similarity=best))
        return groups

    async def _require(self, owner_id: str, memory_id: str) -> Memory:
        def work(session: Session) -> Memory | None:
            memory = session.get(Memory, memory_id)
            return memory if memory is not None and memory.owner_id == owner_id else None

        memory = await in_session(self._engine, work)
        if memory is None:
            raise NotFoundError(f"memory {memory_id!r} not found")
        return memory

    def _decode(self, embedding_enc: str) -> list[float]:
        return json.loads(self._vault.decrypt_str(embedding_enc))

    @staticmethod
    def _to_view(memory: Memory, content: str) -> MemoryView:
        return MemoryView(
            id=memory.id,
            content=content,
            pinned=memory.pinned,
            created_at=memory.created_at,
            updated_at=memory.updated_at,
            has_embedding=memory.embedding_enc is not None,
        )


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    if a.shape != b.shape:
        return 0.0
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denom) if denom else 0.0


def _rrf(dense: dict[str, float], sparse: dict[str, float]) -> dict[str, float]:
    """Reciprocal Rank Fusion of two score maps into one fused score per id."""
    fused: dict[str, float] = {}
    for scores in (dense, sparse):
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        for rank, (mid, _score) in enumerate(ranked, start=1):
            fused[mid] = fused.get(mid, 0.0) + 1.0 / (_RRF_K + rank)
    return fused


def _matched_by(mid: str, dense: dict[str, float], sparse: dict[str, float]) -> str:
    in_dense, in_sparse = mid in dense, mid in sparse
    if in_dense and in_sparse:
        return "both"
    return "semantic" if in_dense else "keyword"
