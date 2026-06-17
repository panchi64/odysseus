"""Cross-chat search — find and read the operator's *other* conversations.

The capability behind the ``conversations_search`` / ``conversations_read`` tools.
Like long-term memory, recall is **hybrid and brute-force**: messages are
encrypted at rest, so there is no DB full-text index — instead we load the owner's
message projections, decrypt them, and score each against the query two ways —

- **dense** (cosine over the per-message embedding, the "by meaning" path), and
- **sparse** (token overlap, the keyword path) —

then fuse the rankings with Reciprocal Rank Fusion and collapse to one hit per
conversation (its best-scoring message becomes the snippet). A message with no
comparable vector (older rows, or one persisted while the embedder was down)
contributes via the sparse signal alone — the same `EMB-2` degrade memory uses.
The scoring primitives are shared with memory in :mod:`services.ranking`.

``read`` reuses the conversation store's own active-path projection so there is no
second copy of the tree/active-leaf logic here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
from sqlalchemy import Engine
from sqlmodel import Session, select

from core.db import in_session
from core.vault import Vault
from models.conversation import Conversation, Message
from services import ranking
from services.conversations import ConversationStore
from services.embeddings import Embedder, decode_vector, embed_query

_SNIPPET_LEN = 240


@dataclass(frozen=True)
class ChatSearchHit:
    """One conversation surfaced by a search, with its best-matching excerpt."""

    conversation_id: str
    title: str | None
    snippet: str
    score: float
    matched_by: str  # semantic | keyword | both
    updated_at: datetime


@dataclass(frozen=True)
class ChatTranscript:
    """A found conversation's active-path turns, rendered for the agent to read."""

    conversation_id: str
    title: str | None
    text: str


class ConversationSearch:
    def __init__(
        self, engine: Engine, vault: Vault, embedder: Embedder, store: ConversationStore
    ) -> None:
        self._engine = engine
        self._vault = vault
        self._embedder = embedder
        self._store = store

    async def search(
        self,
        owner_id: str,
        query: str,
        *,
        limit: int = 5,
        exclude_conversation_id: str | None = None,
    ) -> list[ChatSearchHit]:
        """Hybrid recall across the owner's conversations, best hit per conversation.

        ``exclude_conversation_id`` drops the current thread (the agent already has
        it in context). Ephemeral threads are never searched. A degraded embedder
        collapses cleanly to keyword-only."""
        query_vec, query_model = await embed_query(self._embedder, owner_id, query)
        query_tokens = ranking.tokens(query)

        def work(session: Session) -> list[ChatSearchHit]:
            stmt = (
                select(Message, Conversation)
                .join(Conversation, Message.conversation_id == Conversation.id)  # type: ignore[arg-type]
                .where(Conversation.owner_id == owner_id)
                .where(Conversation.ephemeral == False)  # noqa: E712 — SQL boolean compare
            )
            if exclude_conversation_id is not None:
                stmt = stmt.where(Message.conversation_id != exclude_conversation_id)
            rows = session.exec(stmt).all()
            return self._rank(rows, query_vec, query_model, query_tokens, limit)

        return await in_session(self._engine, work)

    async def read(self, owner_id: str, conversation_id: str) -> ChatTranscript | None:
        """The active-path transcript of one conversation, or None if it isn't the
        owner's. Reuses the store's projection (no duplicate tree logic)."""
        summary = await self._store.get_summary(conversation_id, owner_id)
        if summary is None:
            return None
        views = await self._store.messages_view(conversation_id)
        lines = []
        for view in views:
            content = view.content.strip()
            if content:
                label = "User" if view.role == "user" else "Assistant"
                lines.append(f"{label}: {content}")
        return ChatTranscript(
            conversation_id=conversation_id, title=summary.title, text="\n\n".join(lines)
        )

    # --- internals --------------------------------------------------------

    def _rank(
        self,
        rows: list[tuple[Message, Conversation]],
        query_vec: np.ndarray | None,
        query_model: str | None,
        query_tokens: set[str],
        limit: int,
    ) -> list[ChatSearchHit]:
        dense: dict[str, float] = {}
        sparse: dict[str, float] = {}
        text_by_id: dict[str, str] = {}
        convo_by_id: dict[str, Conversation] = {}
        for message, conversation in rows:
            text = self._vault.decrypt_str(message.text)
            if not text.strip():
                continue
            text_by_id[message.id] = text
            convo_by_id[message.id] = conversation
            overlap = len(query_tokens & ranking.tokens(text))
            if overlap:
                sparse[message.id] = float(overlap)
            # Dense only within the same embedding space (EMB-2), and only when there
            # is actual similarity — a zero/orthogonal vector carries no signal.
            if (
                query_vec is not None
                and message.embedding_enc is not None
                and message.embedding_model == query_model
            ):
                vector = np.asarray(decode_vector(self._vault, message.embedding_enc))
                score = ranking.cosine(query_vec, vector)
                if score > 0:
                    dense[message.id] = score

        fused = ranking.rrf(dense, sparse)
        # Collapse to one hit per conversation: keep its best-scoring message.
        best: dict[str, tuple[str, float]] = {}  # conversation_id -> (message_id, score)
        for message_id, score in fused.items():
            conversation_id = convo_by_id[message_id].id
            if conversation_id not in best or score > best[conversation_id][1]:
                best[conversation_id] = (message_id, score)

        ranked = sorted(best.items(), key=lambda kv: kv[1][1], reverse=True)[:limit]
        hits = []
        for conversation_id, (message_id, score) in ranked:
            conversation = convo_by_id[message_id]
            hits.append(
                ChatSearchHit(
                    conversation_id=conversation_id,
                    title=conversation.title,
                    snippet=self._snippet(text_by_id[message_id], query_tokens),
                    score=score,
                    matched_by=ranking.matched_by(message_id, dense, sparse),
                    updated_at=conversation.updated_at,
                )
            )
        return hits

    @staticmethod
    def _snippet(text: str, query_tokens: set[str]) -> str:
        """A one-line excerpt, windowed around the first matching token when there
        is one, else the head of the message."""
        flat = " ".join(text.split())
        if len(flat) <= _SNIPPET_LEN:
            return flat
        lowered = flat.lower()
        positions = [lowered.find(token) for token in query_tokens]
        hit = min((p for p in positions if p >= 0), default=-1)
        if hit < 0:
            return flat[:_SNIPPET_LEN].rstrip() + "…"
        start = max(0, hit - _SNIPPET_LEN // 3)
        end = start + _SNIPPET_LEN
        excerpt = flat[start:end].strip()
        prefix = "…" if start > 0 else ""
        suffix = "…" if end < len(flat) else ""
        return f"{prefix}{excerpt}{suffix}"
