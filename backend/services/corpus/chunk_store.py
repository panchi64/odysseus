"""The generic chunk store — CRUD + hybrid rank over ``corpus_chunk``.

The shared backend for every *chunked* source (folders now; uploads/gallery/
research/document bodies later). It is the corpus counterpart of ``MemoryStore`` /
``ConversationSearch``: rows are encrypted at rest (text + vector), so recall is the
same **hybrid, brute-force** pass — decrypt the owner's chunks for a source, score
each dense (cosine over the per-chunk vector) and sparse (token overlap), and return
the per-chunk scores *unfused* (``CorpusIndex`` fuses across sources). The scoring
primitives are the shared ones in :mod:`services.ranking`.

Inserts are **idempotent** on ``(owner_id, source_id, content_hash)``: a re-crawl of
unchanged content hashes to the same value and is skipped, so reindex never dupes.
Embedding reuses the one shared loop, ``embed_and_seal_rows(model_cls=CorpusChunk)``.
"""

from __future__ import annotations

import hashlib

import numpy as np
from sqlalchemy import Engine, func, or_
from sqlmodel import Session, delete, select

from core.db import in_session
from core.vault import Vault
from models.corpus import CorpusChunk
from services import ranking
from services.chunking import Chunk
from services.corpus.adapter import CorpusHit
from services.embeddings import Embedder, decode_vector, embed_and_seal_rows


def content_hash(text: str) -> str:
    """The dedup/idempotency key for a chunk — sha256 of its text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class CorpusChunkStore:
    def __init__(self, engine: Engine, vault: Vault, embedder: Embedder) -> None:
        self._engine = engine
        self._vault = vault
        self._embedder = embedder

    # --- write path -------------------------------------------------------

    async def upsert(
        self, owner_id: str, source_kind: str, source_id: str, base_ref: str, chunks: list[Chunk]
    ) -> int:
        """Insert each chunk's sealed text with a null vector, skipping any whose
        content hash already exists for this source (idempotent reindex). Returns
        how many new chunks were inserted."""
        prepared = [
            (
                content_hash(chunk.text),
                f"{base_ref}#{chunk.offset}",
                chunk.ordinal,
                self._vault.encrypt_str(chunk.text),
            )
            for chunk in chunks
            if chunk.text.strip()
        ]

        def work(session: Session) -> int:
            existing = set(
                session.exec(
                    select(CorpusChunk.content_hash).where(
                        CorpusChunk.owner_id == owner_id,
                        CorpusChunk.source_id == source_id,
                    )
                ).all()
            )
            inserted = 0
            for chash, ref, ordinal, text_enc in prepared:
                if chash in existing:
                    continue
                existing.add(chash)  # dedup within this batch too
                session.add(
                    CorpusChunk(
                        owner_id=owner_id,
                        source_kind=source_kind,
                        source_id=source_id,
                        external_ref=ref,
                        content_hash=chash,
                        ordinal=ordinal,
                        text_enc=text_enc,
                    )
                )
                inserted += 1
            return inserted

        return await in_session(self._engine, work)

    async def delete_source(self, owner_id: str, source_id: str) -> None:
        """Drop every chunk a source contributed (folder removal)."""

        def work(session: Session) -> None:
            session.exec(
                delete(CorpusChunk).where(
                    CorpusChunk.owner_id == owner_id,
                    CorpusChunk.source_id == source_id,
                )
            )

        await in_session(self._engine, work)

    async def reembed(
        self,
        owner_id: str,
        source_id: str | None = None,
        *,
        current_model: str | None = None,
        batch_size: int = 64,
    ) -> int:
        """Embed chunks whose vector is missing, or was produced by a model other than
        ``current_model`` (the EMB-2 heal path after an embedding-model change). Scoped
        to ``source_id`` when given, else the owner's whole chunk store. Reuses the one
        shared embed→seal loop. Returns how many chunks were embedded."""

        def pending(session: Session) -> list[tuple[str, str]]:
            query = select(CorpusChunk).where(CorpusChunk.owner_id == owner_id)
            if source_id is not None:
                query = query.where(CorpusChunk.source_id == source_id)
            if current_model is None:
                query = query.where(CorpusChunk.embedding_enc.is_(None))  # type: ignore[union-attr]
            else:
                query = query.where(
                    or_(
                        CorpusChunk.embedding_enc.is_(None),  # type: ignore[union-attr]
                        CorpusChunk.embedding_model != current_model,
                    )
                )
            rows = session.exec(query).all()
            return [(row.id, self._vault.decrypt_str(row.text_enc)) for row in rows]

        rows = await in_session(self._engine, pending)
        items = [(rid, text) for rid, text in rows if text.strip()]
        return await embed_and_seal_rows(
            engine=self._engine,
            vault=self._vault,
            embedder=self._embedder,
            owner_id=owner_id,
            model_cls=CorpusChunk,
            pending=items,
            batch_size=batch_size,
        )

    # --- read path --------------------------------------------------------

    async def count(self, owner_id: str, source_id: str) -> int:
        """How many chunks a source has indexed (never decrypts)."""

        def work(session: Session) -> int:
            return session.exec(
                select(func.count())
                .select_from(CorpusChunk)
                .where(CorpusChunk.owner_id == owner_id, CorpusChunk.source_id == source_id)
            ).one()

        return await in_session(self._engine, work)

    async def count_all(self, owner_id: str) -> int:
        """Total chunks across every chunked source (the corpus-stats readout)."""

        def work(session: Session) -> int:
            return session.exec(
                select(func.count())
                .select_from(CorpusChunk)
                .where(CorpusChunk.owner_id == owner_id)
            ).one()

        return await in_session(self._engine, work)

    async def retrieve(
        self,
        owner_id: str,
        source_kind: str,
        query_vec: np.ndarray | None,
        query_model: str | None,
        query_tokens: set[str],
        *,
        limit: int,
        source_id: str | None = None,
    ) -> list[CorpusHit]:
        """Hybrid recall over a source's chunks, scored but **unfused** (the index
        fuses across sources). Filtered to ``source_kind`` (and ``source_id`` when a
        single source is targeted). A degraded query vector collapses to sparse-only."""

        def work(session: Session) -> list[CorpusHit]:
            query = select(CorpusChunk).where(
                CorpusChunk.owner_id == owner_id,
                CorpusChunk.source_kind == source_kind,
            )
            if source_id is not None:
                query = query.where(CorpusChunk.source_id == source_id)
            rows = session.exec(query).all()
            return self._rank(rows, query_vec, query_model, query_tokens, limit)

        return await in_session(self._engine, work)

    def _rank(
        self,
        rows: list[CorpusChunk],
        query_vec: np.ndarray | None,
        query_model: str | None,
        query_tokens: set[str],
        limit: int,
    ) -> list[CorpusHit]:
        dense: dict[str, float] = {}
        sparse: dict[str, float] = {}
        by_id: dict[str, CorpusChunk] = {}
        text_by_id: dict[str, str] = {}
        for row in rows:
            text = self._vault.decrypt_str(row.text_enc)
            if not text.strip():
                continue
            by_id[row.id] = row
            text_by_id[row.id] = text
            overlap = len(query_tokens & ranking.tokens(text))
            if overlap:
                sparse[row.id] = float(overlap)
            # Dense only within the same embedding space (EMB-2), and only when there
            # is actual similarity — a zero/orthogonal vector carries no signal.
            if (
                query_vec is not None
                and row.embedding_enc is not None
                and row.embedding_model == query_model
            ):
                vector = np.asarray(decode_vector(self._vault, row.embedding_enc))
                score = ranking.cosine(query_vec, vector)
                if score > 0:
                    dense[row.id] = score

        # Fuse this source's own dense + sparse signals with RRF (same hybrid memory
        # and conversation recall use), so cosine and keyword overlap combine by rank
        # rather than letting the larger raw number win. The index then fuses the
        # already-ranked sources together.
        fused = ranking.rrf(dense, sparse)
        ordered = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:limit]
        hits: list[CorpusHit] = []
        for cid, _score in ordered:
            row = by_id[cid]
            hits.append(
                CorpusHit(
                    gid=f"{row.source_id}:{row.external_ref}",
                    source_id=row.source_id,
                    ref=row.external_ref,
                    text=text_by_id[cid],
                    dense_score=dense.get(cid),
                    sparse_score=sparse.get(cid),
                    matched_by=ranking.matched_by(cid, dense, sparse),
                )
            )
        return hits
