"""Conversation store — the in-memory working set + write-behind to the DB.

While a conversation is active its full ``ModelMessage`` history lives in memory
(the fast working set), so a turn continues with zero DB reads on the hot path.
As each turn completes, its new messages are copied onto a queue that a
background drainer writes to the DB off the critical path. The DB is the durable
record; memory is the fast one. A cold conversation rehydrates from the DB once,
then runs at memory speed.

Content is **encrypted at rest**: the durable text and blob are encrypted by the
drainer, just before the write, not on the hot path. The working set stays
plaintext (it already holds plaintext in memory); the hot path only projects and
serializes. Encrypting in the drainer keeps it on the **lock-aware** side of the
queue — if the vault locks mid-turn the write parks until unlock instead of
erroring and losing the turn. Structural metadata (ids, timestamps, owner, seq,
kind) stays plaintext so the DB can still index and order. The drainer is a
lock-aware :class:`~core.worker.WriteBehindWorker` — it parks while the vault is
locked and retries failed writes rather than dropping them.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from pydantic import TypeAdapter
from pydantic_ai import ModelMessage
from sqlalchemy import Engine
from sqlmodel import Session, select

from core.db import in_session
from core.vault import Vault
from core.worker import WriteBehindWorker
from models.conversation import Conversation, Message

logger = logging.getLogger(__name__)

_MESSAGE = TypeAdapter(ModelMessage)
_TEXT_PARTS = {"TextPart", "UserPromptPart", "SystemPromptPart"}

# A persistence-ready row, still plaintext: (kind, text, serialized blob). The
# drainer encrypts text + blob just before the write (lock-aware side of the
# queue), so a vault lock mid-turn parks the write rather than losing it.
_Row = tuple[str, str, str]
# A write-behind job: (conversation_id, seq of the first row, the rows). The seq
# base is taken from the authoritative in-memory working set at record time, so
# the drainer never has to count rows (and the two can't diverge).
_PersistJob = tuple[str, int, list[_Row]]


def _project(message: ModelMessage) -> tuple[str, str]:
    """Derive (kind, text) for listing/search from a ModelMessage."""
    kind = getattr(message, "kind", "")
    text = " ".join(
        part.content
        for part in message.parts
        if type(part).__name__ in _TEXT_PARTS and isinstance(getattr(part, "content", None), str)
    )
    return kind, text


class ConversationStore:
    def __init__(self, engine: Engine, vault: Vault) -> None:
        self._engine = engine
        self._vault = vault
        self._cache: dict[str, list[ModelMessage]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._worker: WriteBehindWorker[_PersistJob] = WriteBehindWorker(
            self._persist,
            name="persistence-drainer",
            unlocked=vault.unlocked_event,
            on_drop=self._on_drop,
        )

    async def start(self) -> None:
        await self._worker.start()

    async def stop(self) -> None:
        await self._worker.stop()

    async def create_conversation(self, owner_id: str, title: str | None = None) -> str:
        def work(session: Session) -> str:
            conversation = Conversation(owner_id=owner_id, title=title)
            session.add(conversation)
            session.flush()
            return conversation.id

        conversation_id = await in_session(self._engine, work)
        self._cache[conversation_id] = []
        return conversation_id

    async def exists(self, conversation_id: str, owner_id: str) -> bool:
        """Whether ``conversation_id`` names a conversation owned by ``owner_id``."""
        def work(session: Session) -> bool:
            conversation = session.get(Conversation, conversation_id)
            return conversation is not None and conversation.owner_id == owner_id

        return await in_session(self._engine, work)

    async def history(self, conversation_id: str) -> list[ModelMessage]:
        """The conversation's message history — from the cache, or rehydrated once."""
        cached = self._cache.get(conversation_id)
        if cached is not None:
            return list(cached)

        # Serialize rehydration per conversation and re-check inside the lock, so a
        # concurrent record()/history() can't be clobbered by a stale DB snapshot.
        async with self._locks.setdefault(conversation_id, asyncio.Lock()):
            cached = self._cache.get(conversation_id)
            if cached is not None:
                return list(cached)

            def work(session: Session) -> list[str]:
                rows = session.exec(
                    select(Message)
                    .where(Message.conversation_id == conversation_id)
                    .order_by(Message.seq)
                ).all()
                return [row.blob for row in rows]

            blobs = await in_session(self._engine, work)
            messages = [_MESSAGE.validate_json(self._vault.decrypt_str(blob)) for blob in blobs]
            self._cache[conversation_id] = messages
            return list(messages)

    def record(self, conversation_id: str, new_messages: list[ModelMessage]) -> None:
        """Hot path: extend the working set and queue the durable write.

        Only projects and serializes here (no vault) — the drainer encrypts just
        before the write, on the lock-aware side of the queue."""
        if not new_messages:
            return
        working = self._cache.setdefault(conversation_id, [])
        base = len(working)  # the seq of the first new message (working set is the truth)
        working.extend(new_messages)
        rows: list[_Row] = []
        for message in new_messages:
            kind, text = _project(message)
            blob = _MESSAGE.dump_json(message).decode()
            rows.append((kind, text, blob))
        self._worker.submit((conversation_id, base, rows))

    async def _persist(self, job: _PersistJob) -> None:
        conversation_id, base, rows = job

        def work(session: Session) -> None:
            for offset, (kind, text, blob) in enumerate(rows):
                session.add(
                    Message(
                        conversation_id=conversation_id,
                        seq=base + offset,
                        kind=kind,
                        text=self._vault.encrypt_str(text),
                        blob=self._vault.encrypt_str(blob),
                    )
                )
            conversation = session.get(Conversation, conversation_id)
            if conversation is not None:
                conversation.updated_at = datetime.now(UTC)

        await in_session(self._engine, work)

    def _on_drop(self, job: _PersistJob, exc: Exception) -> None:
        conversation_id, base, rows = job
        logger.error(
            "permanently failed to persist %d messages for conversation %s (seq %d+): %s",
            len(rows),
            conversation_id,
            base,
            exc,
        )
