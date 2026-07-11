"""The attention surface's substrate — an in-memory index + ring-buffered live stream,
backed by a lock-aware write-behind drainer for durability.

Mirrors two existing disciplines rather than inventing a third:

- **`runs/stream.py`'s live-fan-out discipline**, for the stream half: `_emit` is
  synchronous and `subscribe` registers-then-snapshots with no `await` between, so a
  subscriber can never observe a gap or a duplicate. Unlike a `RunStream` (buffered for
  one run's lifetime, then closed), this stream is process-lifetime and its buffer is a
  true ring — bounded, oldest evicted — since it isn't scoped to one short-lived run.
- **`services/conversations.py`'s memory-fast/DB-durable split**, for the record half:
  an in-memory index is the authoritative read path (what `list_notifications`,
  `mark_read`, etc. answer against, immediately and consistently), while a background
  `WriteBehindWorker` persists it off the critical path, encrypting the sealed fields
  only in the drainer (the lock-aware side of the queue) so a locked vault parks the
  write instead of losing it. Read/resolve mutations ride the **same** drainer queue as
  their creating insert, so an update can never race ahead of — and silently no-op
  against — a row that hasn't landed in the DB yet.

This module only records and streams what it's told. *Whether* to notify (the emit
policy: which run outcomes are noteworthy, whether anyone was already watching) lives
with the callers — the engine, the run registry, the approval routes — not here.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal

from sqlalchemy import Engine
from sqlmodel import Session, select

from core.db import in_session
from core.vault import Vault
from core.worker import WriteBehindWorker
from models._fields import new_id, utcnow
from models.notification import Notification

logger = logging.getLogger(__name__)

# Per-subscriber backlog cap before a stalled consumer is dropped (mirrors
# `runs/stream.py`'s `_SUBSCRIBER_QUEUE_MAX`).
_SUBSCRIBER_QUEUE_MAX = 1024

# The stream's ring-buffer depth. Unlike a per-run `RunStream` (buffered for the run's
# whole lifetime), this surface lives as long as the process — a true ring keeps replay
# bounded; a reconnect past the horizon simply misses the oldest events (the same
# in-memory-only tradeoff `runs/stream.py` already licenses).
_RING_BUFFER_MAX = 500


@dataclass(frozen=True)
class NotificationView:
    """A decrypted notification — the shape every read returns (the owner sees their
    own content in the clear, like documents/memory)."""

    id: str
    owner_id: str
    kind: str
    title: str
    body: str | None
    conversation_id: str | None
    run_id: str | None
    task_id: str | None
    created_at: datetime
    read_at: datetime | None
    resolved_at: datetime | None


@dataclass(frozen=True, slots=True)
class NotificationEvent:
    """One stamped stream event — this surface's own seq/ts, mirroring `runs.Event`
    but carrying a nested `notification` payload rather than a flat body (the wire
    envelope needs the full current view, not just what changed)."""

    seq: int
    ts: datetime
    kind: Literal["created", "updated"]
    notification: NotificationView


@dataclass
class _Job:
    """A unit of durable work. ``create`` inserts a fresh row (encrypting title/body
    just before the write); ``update`` writes back the current read/resolved state —
    always the *whole* current state, never a delta, so replaying it is idempotent
    even if two updates for the same id end up queued back to back."""

    op: Literal["create", "update"]
    id: str
    owner_id: str = ""
    notif_kind: str = ""
    title: str = ""
    body: str | None = None
    conversation_id: str | None = None
    run_id: str | None = None
    task_id: str | None = None
    created_at: datetime | None = None
    read_at: datetime | None = None
    resolved_at: datetime | None = None


class NotificationService:
    def __init__(
        self,
        engine: Engine,
        vault: Vault,
        *,
        ring_buffer_max: int = _RING_BUFFER_MAX,
    ) -> None:
        self._engine = engine
        self._vault = vault
        self._cache: dict[str, NotificationView] = {}
        self._buffer: deque[NotificationEvent] = deque(maxlen=ring_buffer_max)
        self._seq = 0
        self._subscribers: set[asyncio.Queue[NotificationEvent | None]] = set()
        self._worker: WriteBehindWorker[_Job] = WriteBehindWorker(
            self._persist,
            name="notifications-drainer",
            unlocked=vault.unlocked_event,
            on_drop=self._on_drop,
        )
        self._rehydrate_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        await self._worker.start()
        # Best-effort, off the critical path: once unlocked, lift prior history into
        # the cache so a restart's REST/unread state reflects it, not just what's
        # notified after this boot (mirrors the embedding backfill's posture).
        self._rehydrate_task = asyncio.create_task(
            self._rehydrate(), name="notifications-rehydrate"
        )

    async def stop(self) -> None:
        if self._rehydrate_task is not None and not self._rehydrate_task.done():
            self._rehydrate_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._rehydrate_task
        await self._worker.stop()

    @property
    def last_seq(self) -> int:
        return self._seq

    # --- writes -------------------------------------------------------------

    async def notify(
        self,
        owner_id: str,
        kind: str,
        title: str,
        body: str | None = None,
        *,
        conversation_id: str | None = None,
        run_id: str | None = None,
        task_id: str | None = None,
    ) -> NotificationView:
        """Record a new notification: cached + streamed immediately, persisted off the
        critical path."""
        view = NotificationView(
            id=new_id(),
            owner_id=owner_id,
            kind=kind,
            title=title,
            body=body,
            conversation_id=conversation_id,
            run_id=run_id,
            task_id=task_id,
            created_at=utcnow(),
            read_at=None,
            resolved_at=None,
        )
        self._cache[view.id] = view
        self._emit("created", view)
        self._worker.submit(
            _Job(
                op="create",
                id=view.id,
                owner_id=owner_id,
                notif_kind=kind,
                title=title,
                body=body,
                conversation_id=conversation_id,
                run_id=run_id,
                task_id=task_id,
                created_at=view.created_at,
            )
        )
        return view

    async def mark_read(self, owner_id: str, ids: list[str]) -> int:
        """Mark specific notifications read. Ids that don't exist, aren't the owner's,
        or are already read are silently skipped — idempotent, never an error. Returns
        how many actually changed."""
        wanted = set(ids)
        return self._mark_read(owner_id, lambda view: view.id in wanted)

    async def mark_all_read(self, owner_id: str) -> int:
        """Mark every one of the owner's unread notifications read. Returns how many
        changed."""
        return self._mark_read(owner_id, lambda _view: True)

    async def resolve_for_run(self, owner_id: str, run_id: str) -> list[NotificationView]:
        """Resolve every one of the run's not-yet-resolved notifications (in practice
        at most its one `approval_needed`) — the approval was decided by some path, or
        the run reached terminal without one ever being decided. Returns the resolved
        views (empty if the run had none pending — idempotent)."""
        now = utcnow()
        resolved: list[NotificationView] = []
        for notif_id, view in list(self._cache.items()):
            if view.owner_id != owner_id or view.run_id != run_id or view.resolved_at is not None:
                continue
            updated = replace(view, resolved_at=now)
            self._cache[notif_id] = updated
            resolved.append(updated)
        for view in resolved:
            self._emit("updated", view)
            self._queue_update(view)
        return resolved

    # --- reads ----------------------------------------------------------------

    async def list_notifications(
        self,
        owner_id: str,
        *,
        limit: int = 50,
        before: datetime | None = None,
        unread_only: bool = False,
    ) -> tuple[list[NotificationView], int]:
        """Newest-first page of the owner's notifications, plus their current unread
        count. Reads the in-memory index — the same authoritative state `notify` /
        `mark_read` / etc. just updated — rather than a DB round-trip that could lag
        behind a write still sitting in the drainer's queue."""
        owned = [v for v in self._cache.values() if v.owner_id == owner_id]
        unread_count = sum(1 for v in owned if v.read_at is None)
        if unread_only:
            owned = [v for v in owned if v.read_at is None]
        if before is not None:
            owned = [v for v in owned if v.created_at < before]
        owned.sort(key=lambda v: v.created_at, reverse=True)
        return owned[:limit], unread_count

    async def subscribe(self, after_seq: int = 0) -> AsyncIterator[NotificationEvent]:
        """Replay ring-buffered events after ``after_seq`` then stream live ones. Never
        ends on its own — this surface is process-lifetime, not tied to one run's
        terminal state — so iteration only stops when the caller does (a client
        disconnect cancelling the pump task, in the SSE route)."""
        queue: asyncio.Queue[NotificationEvent | None] = asyncio.Queue(
            maxsize=_SUBSCRIBER_QUEUE_MAX
        )
        # --- atomic: register before snapshot, no await between ---
        self._subscribers.add(queue)
        backlog = [e for e in self._buffer if e.seq > after_seq] if after_seq > 0 else list(
            self._buffer
        )
        # ------------------------------------------------------------
        try:
            for event in backlog:
                yield event
            while True:
                event = await queue.get()
                if event is None:  # never sent in practice (no process-wide "close"),
                    return  # kept symmetric with RunStream for a future graceful-stop.
                yield event
        finally:
            self._subscribers.discard(queue)

    # --- internals --------------------------------------------------------

    def _mark_read(self, owner_id: str, predicate: Callable[[NotificationView], bool]) -> int:
        now = utcnow()
        changed: list[NotificationView] = []
        for notif_id, view in list(self._cache.items()):
            if view.owner_id != owner_id or view.read_at is not None or not predicate(view):
                continue
            updated = replace(view, read_at=now)
            self._cache[notif_id] = updated
            changed.append(updated)
        for view in changed:
            self._emit("updated", view)
            self._queue_update(view)
        return len(changed)

    def _emit(
        self, kind: Literal["created", "updated"], view: NotificationView
    ) -> NotificationEvent:
        """Stamp, ring-buffer, and fan out. Synchronous and atomic — no `await` between
        a mutation landing in the cache and this fan-out, so `subscribe` can never
        observe a state between the two (mirrors `RunStream.emit`)."""
        self._seq += 1
        event = NotificationEvent(seq=self._seq, ts=utcnow(), kind=kind, notification=view)
        self._buffer.append(event)  # a bounded deque evicts the oldest on overflow
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                self._drop_slow(queue)
        return event

    def _drop_slow(self, queue: asyncio.Queue[NotificationEvent | None]) -> None:
        """Evict a subscriber that isn't keeping up — it can reconnect and replay from
        the ring buffer (mirrors `RunStream._drop_slow`)."""
        self._subscribers.discard(queue)
        while not queue.empty():
            queue.get_nowait()
        queue.put_nowait(None)

    def _queue_update(self, view: NotificationView) -> None:
        self._worker.submit(
            _Job(op="update", id=view.id, read_at=view.read_at, resolved_at=view.resolved_at)
        )

    def _on_drop(self, job: _Job, exc: Exception) -> None:
        logger.error(
            "notifications: dropped a %s write for %s after retries: %s", job.op, job.id, exc
        )

    async def _rehydrate(self) -> None:
        await self._vault.unlocked_event.wait()
        try:
            rows = await in_session(
                self._engine, lambda session: session.exec(select(Notification)).all()
            )
        except Exception:
            logger.exception("notifications: rehydrate from DB failed")
            return
        for row in rows:
            if row.id in self._cache:  # a notify() since boot already cached it fresher
                continue
            self._cache[row.id] = self._row_to_view(row)

    def _row_to_view(self, row: Notification) -> NotificationView:
        return NotificationView(
            id=row.id,
            owner_id=row.owner_id,
            kind=row.kind,
            title=self._vault.decrypt_str(row.title_enc),
            body=self._vault.decrypt_str(row.body_enc) if row.body_enc is not None else None,
            conversation_id=row.conversation_id,
            run_id=row.run_id,
            task_id=row.task_id,
            created_at=row.created_at,
            read_at=row.read_at,
            resolved_at=row.resolved_at,
        )

    async def _persist(self, job: _Job) -> None:
        if job.op == "create":

            def work(session: Session) -> None:
                session.add(
                    Notification(
                        id=job.id,
                        owner_id=job.owner_id,
                        kind=job.notif_kind,
                        title_enc=self._vault.encrypt_str(job.title),
                        body_enc=(
                            self._vault.encrypt_str(job.body) if job.body is not None else None
                        ),
                        conversation_id=job.conversation_id,
                        run_id=job.run_id,
                        task_id=job.task_id,
                        created_at=job.created_at,
                    )
                )

            await in_session(self._engine, work)
        else:

            def work(session: Session) -> None:
                row = session.get(Notification, job.id)
                if row is None:  # the create hasn't landed (shouldn't happen — the
                    return  # single-queue FIFO orders it first) — never resurrect it.
                row.read_at = job.read_at
                row.resolved_at = job.resolved_at
                session.add(row)

            await in_session(self._engine, work)
