"""The agent's task list, persisted per conversation and streamed as it changes.

``pydantic_ai_harness.Planning`` owns the tools and the model-facing behaviour; it depends
only on a six-method :class:`~pydantic_ai_harness.planning.PlanStore` protocol. This is our
implementation of it — sealed under the vault, keyed by conversation, and emitting a
``plan.updated`` event on every mutation so the chat surface can render the list live.

**Every mutation emits, including the bulk replace.** The harness's own stores leave
``set_items`` event-silent (it is a wholesale replacement), which would be a real hole
here: ``write_plan`` is the tool a model reaches for first and most often, so a surface
built on events alone would sit empty through exactly the call that matters. Emitting from
the store rather than from a hook means every path — bulk or granular — reports uniformly.

**The event carries the whole list, not a delta.** The per-run stream is replayable from
any sequence number (``runs/``), so a full-state event is idempotent on replay and needs no
ordering rules; the list is a handful of short strings, and correctness here is worth more
than the bytes.

**A locked vault degrades to no plan rather than an error.** Planning is an aid to the
turn, not the turn itself: a run that cannot read its plan should carry on without one
instead of failing, which is why reads fall back to empty and writes are dropped.
"""

from __future__ import annotations

import asyncio
import json
import logging

from pydantic_ai_harness.planning import PlanItem, PlanStore, TaskStatus, render_plan
from sqlalchemy import Engine
from sqlmodel import Session, select

from core.db import in_session
from core.vault import Vault, VaultError, VaultLocked
from models._fields import new_id, utcnow
from models.plan import ConversationPlan
from runs import PlanUpdated, Run

logger = logging.getLogger(__name__)


def _dump(items: list[PlanItem]) -> str:
    return json.dumps([item.model_dump(mode="json") for item in items])


def _load(raw: str) -> list[PlanItem]:
    return [PlanItem.model_validate(row) for row in json.loads(raw)]


def plan_payload(items: list[PlanItem]) -> list[dict]:
    """The task list as the frontend consumes it — the same shape on the event and on the
    REST backfill, so a reload rebuilds exactly what the stream was drawing."""
    return [
        {
            "id": item.id,
            "content": item.content,
            "status": (
                item.status.value if isinstance(item.status, TaskStatus) else str(item.status)
            ),
            "active_form": item.active_form,
        }
        for item in items
    ]


def accepted_plan_prompt(items: list[PlanItem]) -> str:
    """The message that starts the turn after the operator accepts a plan.

    A Plan-level turn ends with a plan and no way to act on it; accepting it raises the
    thread's level and sends this. It is written in the operator's voice because it *is*
    their message — the turn it opens is an ordinary one, so the acceptance lands in the
    transcript where anyone reading the thread later can see what was agreed to and when.

    The list is restated even though the current one already rides at the tail of every
    turn's prompt (``tools/plan.py``). That block is live and the model rewrites it as it
    works; this is the version that was accepted, fixed in the history.
    """
    return (
        "I've reviewed this plan and I'm accepting it. Carry it out now, keeping the "
        f"task list accurate as you go.\n\n{render_plan(items)}"
    )


class ConversationPlans:
    """Reads and writes the stored plan for a conversation. Owner-scoped; vault-sealed."""

    def __init__(self, db_engine: Engine, vault: Vault) -> None:
        self._db = db_engine
        self._vault = vault
        self._locks: dict[str, asyncio.Lock] = {}

    def lock_for(self, conversation_id: str) -> asyncio.Lock:
        """The mutation lock for one conversation's plan.

        Every write is a read-modify-write of the whole list across two awaits, and a
        model may emit several plan calls in a single response that Pydantic AI then runs
        **concurrently** — without this, two "mark task done" calls interleave and the
        second silently discards the first. Per conversation rather than global so two
        threads working on different chats never wait on each other.
        """
        lock = self._locks.get(conversation_id)
        if lock is None:
            lock = self._locks[conversation_id] = asyncio.Lock()
        return lock

    async def items(self, owner_id: str, conversation_id: str) -> list[PlanItem]:
        def work(session: Session) -> str | None:
            row = session.exec(
                select(ConversationPlan)
                .where(ConversationPlan.owner_id == owner_id)
                .where(ConversationPlan.conversation_id == conversation_id)
            ).first()
            return row.items_enc if row else None

        sealed = await in_session(self._db, work)
        if sealed is None:
            return []
        try:
            return _load(self._vault.decrypt_str(sealed))
        except (VaultLocked, VaultError):
            logger.debug("plan unreadable for %s: vault locked", conversation_id)
            return []

    async def delete_for_conversation(self, owner_id: str, conversation_id: str) -> None:
        """Drop a thread's plan when the thread goes.

        The plan restates what the operator asked for, so leaving it behind would keep a
        description of a deleted conversation on disk — the same reason the delete path
        already purges the View history and the sandbox workspace. Works while the vault
        is locked: it only destroys.
        """

        def work(session: Session) -> None:
            for row in session.exec(
                select(ConversationPlan)
                .where(ConversationPlan.owner_id == owner_id)
                .where(ConversationPlan.conversation_id == conversation_id)
            ).all():
                session.delete(row)

        await in_session(self._db, work)
        self._locks.pop(conversation_id, None)

    async def replace(
        self, owner_id: str, conversation_id: str, items: list[PlanItem]
    ) -> bool:
        """Store ``items``; ``False`` when the vault was locked and nothing was written.

        The caller needs the distinction: announcing a change that was silently dropped
        would leave the panel showing tasks a reload proves were never saved.
        """
        try:
            sealed = self._vault.encrypt_str(_dump(items))
        except (VaultLocked, VaultError):
            logger.debug("plan not stored for %s: vault locked", conversation_id)
            return False

        def work(session: Session) -> None:
            row = session.exec(
                select(ConversationPlan)
                .where(ConversationPlan.owner_id == owner_id)
                .where(ConversationPlan.conversation_id == conversation_id)
            ).first()
            if row is None:
                row = ConversationPlan(
                    id=new_id(),
                    owner_id=owner_id,
                    conversation_id=conversation_id,
                    items_enc=sealed,
                )
            else:
                row.items_enc = sealed
            row.updated_at = utcnow()
            session.add(row)

        await in_session(self._db, work)
        return True


class ConversationPlanStore(PlanStore):
    """One conversation's plan, as the harness's ``PlanStore``.

    Bound to a run so each mutation can emit; the six protocol methods are expressed over
    read-modify-write of the whole list, which keeps the stored form and the emitted form
    the same thing and leaves no path that changes one without the other.
    """

    def __init__(
        self,
        plans: ConversationPlans,
        *,
        owner_id: str,
        conversation_id: str,
        run: Run | None = None,
    ) -> None:
        self._plans = plans
        self._owner_id = owner_id
        self._conversation_id = conversation_id
        self._run = run
        # Held across each read-modify-write below. It lives on the shared `plans` handle,
        # not here, because a fresh store object is built per run — a lock owned by this
        # object would be a different lock for every caller and guard nothing.
        self._lock = plans.lock_for(conversation_id)

    def bind_run(self, run: Run | None) -> None:
        """Point emissions at the run currently working this conversation.

        The store outlives any one turn (it is cached per conversation so the plan tools
        keep their identity), while the `Run` it emits on is per turn — without this, the
        second turn's plan changes would stream onto the first turn's dead stream and the
        panel would stop updating live.
        """
        self._run = run

    async def get_items(self) -> list[PlanItem]:
        return await self._plans.items(self._owner_id, self._conversation_id)

    async def set_items(self, items: list[PlanItem]) -> None:
        # A wholesale replace reads nothing first, so it needs no lock of its own — but it
        # still takes one so it can't land in the middle of another call's read-modify-write.
        async with self._lock:
            await self._commit(list(items))

    async def get_item(self, item_id: str) -> PlanItem | None:
        return next((i for i in await self.get_items() if i.id == item_id), None)

    async def add_item(self, item: PlanItem) -> PlanItem:
        async with self._lock:
            items = await self.get_items()
            if any(existing.id == item.id for existing in items):
                # The protocol requires this: a duplicate id would shadow the original and
                # make later updates land on one of them at random.
                raise ValueError(f"plan item {item.id!r} already exists")
            items.append(item)
            await self._commit(items)
        return item

    async def update_item(
        self,
        item_id: str,
        *,
        content: str | None = None,
        status: TaskStatus | None = None,
        active_form: str | None = None,
        parent_id: str | None = None,
        depends_on: list[str] | None = None,
    ) -> PlanItem | None:
        async with self._lock:
            items = await self.get_items()
            updated: PlanItem | None = None
            for index, item in enumerate(items):
                if item.id != item_id:
                    continue
                updated = item.model_copy(
                    update={
                        key: value
                        for key, value in (
                            ("content", content),
                            ("status", status),
                            ("active_form", active_form),
                            ("parent_id", parent_id),
                            ("depends_on", depends_on),
                        )
                        if value is not None
                    }
                )
                items[index] = updated
                break
            if updated is None:
                return None
            await self._commit(items)
        return updated

    async def remove_item(self, item_id: str) -> bool:
        async with self._lock:
            items = await self.get_items()
            remaining = [i for i in items if i.id != item_id]
            if len(remaining) == len(items):
                return False
            await self._commit(remaining)
        return True

    async def _commit(self, items: list[PlanItem]) -> None:
        stored = await self._plans.replace(self._owner_id, self._conversation_id, items)
        # Only announce what actually landed. A locked vault drops the write silently, and
        # emitting anyway would draw a panel that a reload contradicts.
        if stored and self._run is not None:
            self._run.emit(PlanUpdated(items=plan_payload(items)))
