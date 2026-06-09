"""Conversation store — the in-memory working set + write-behind to the DB.

While a conversation is active its full ``ModelMessage`` history lives in memory
(the fast working set), so a turn continues with zero DB reads on the hot path.
As each turn completes, its new messages are copied onto a queue that a
background drainer writes to the DB off the critical path. The DB is the durable
record; memory is the fast one. A cold conversation rehydrates from the DB once,
then runs at memory speed.
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import suppress
from datetime import UTC, datetime

from pydantic import TypeAdapter
from pydantic_ai import ModelMessage
from pydantic_core import to_jsonable_python
from sqlalchemy import Engine, func
from sqlmodel import Session, select

from core.db import in_session
from models.conversation import Conversation, Message

logger = logging.getLogger(__name__)

_MESSAGE = TypeAdapter(ModelMessage)
_TEXT_PARTS = {"TextPart", "UserPromptPart", "SystemPromptPart"}


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
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._cache: dict[str, list[ModelMessage]] = {}
        self._queue: asyncio.Queue[tuple[str, list[ModelMessage]]] = asyncio.Queue()
        self._drainer: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._drainer = asyncio.create_task(self._drain(), name="persistence-drainer")

    async def stop(self) -> None:
        await self._queue.join()  # flush pending writes before shutdown
        if self._drainer is not None:
            self._drainer.cancel()
            with suppress(asyncio.CancelledError):
                await self._drainer

    async def create_conversation(self, owner_id: str, title: str | None = None) -> str:
        def work(session: Session) -> str:
            conversation = Conversation(owner_id=owner_id, title=title)
            session.add(conversation)
            session.flush()
            return conversation.id

        conversation_id = await in_session(self._engine, work)
        self._cache[conversation_id] = []
        return conversation_id

    async def history(self, conversation_id: str) -> list[ModelMessage]:
        """The conversation's message history — from the cache, or rehydrated once."""
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
        messages = [_MESSAGE.validate_json(blob) for blob in blobs]
        self._cache[conversation_id] = messages
        return list(messages)

    def record(self, conversation_id: str, new_messages: list[ModelMessage]) -> None:
        """Hot path: extend the working set and queue the durable write."""
        if not new_messages:
            return
        self._cache.setdefault(conversation_id, []).extend(new_messages)
        self._queue.put_nowait((conversation_id, list(new_messages)))

    async def _drain(self) -> None:
        while True:
            conversation_id, messages = await self._queue.get()
            try:
                await self._persist(conversation_id, messages)
            except Exception:  # noqa: BLE001 — a bad write must not kill the drainer
                logger.exception("failed to persist messages for %s", conversation_id)
            finally:
                self._queue.task_done()

    async def _persist(self, conversation_id: str, messages: list[ModelMessage]) -> None:
        def work(session: Session) -> None:
            # The drainer is single-threaded, so the row count is the next seq.
            base = session.scalar(
                select(func.count(Message.id)).where(Message.conversation_id == conversation_id)
            )
            base = base or 0
            for offset, message in enumerate(messages):
                kind, text = _project(message)
                session.add(
                    Message(
                        conversation_id=conversation_id,
                        seq=base + offset,
                        kind=kind,
                        text=text,
                        blob=json.dumps(to_jsonable_python(message)),
                    )
                )
            conversation = session.get(Conversation, conversation_id)
            if conversation is not None:
                conversation.updated_at = datetime.now(UTC)

        await in_session(self._engine, work)
