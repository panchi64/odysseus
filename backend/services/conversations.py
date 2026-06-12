"""Conversation store — the in-memory working tree + write-behind to the DB.

While a conversation is active its full message **tree** lives in memory (the fast
working set), so a turn continues with zero DB reads on the hot path. As each turn
completes, its new messages are copied onto a queue that a background drainer
writes to the DB off the critical path. The DB is the durable record; memory is
the fast one. A cold conversation rehydrates from the DB once, then runs at memory
speed.

The tree is what makes regenerate / edit / rewind work. Every node points at its
predecessor (``parent_id``); **siblings sharing a parent are versions.** The
conversation's *active leaf* is the tip of the path the operator is viewing —
walking it to the root yields the active history (the flat list the agent runs
against). Navigation never invents history: regenerate/edit/rewind all just move
the active leaf, then a normal turn records its messages as a new branch off it.

Content is **encrypted at rest**: the durable text and blob are encrypted by the
drainer, just before the write, not on the hot path. The working set stays
plaintext (it already holds plaintext in memory); the hot path only projects and
serializes. Encrypting in the drainer keeps it on the **lock-aware** side of the
queue — if the vault locks mid-turn the write parks until unlock instead of
erroring and losing the turn. Structural metadata (ids, parent ids, timestamps,
owner, seq, kind, the active-leaf pointer) stays plaintext so the DB can still
index and order. The drainer is a lock-aware :class:`~core.worker.WriteBehindWorker`
— it parks while the vault is locked and retries failed writes rather than
dropping them. Active-leaf moves and deletes ride the same queue so they stay
ordered behind the message writes that precede them.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from pydantic import TypeAdapter
from pydantic_ai import ModelMessage, ModelRequest, UserPromptPart
from sqlalchemy import Engine, delete, func
from sqlalchemy import text as sa_text
from sqlmodel import Session, select

from core.db import in_session
from core.vault import Vault
from core.worker import WriteBehindWorker
from models._fields import new_id
from models.conversation import Conversation, Message
from services.conversation_view import MessageView, project_tree

logger = logging.getLogger(__name__)

_MESSAGE = TypeAdapter(ModelMessage)
_TEXT_PARTS = {"TextPart", "UserPromptPart", "SystemPromptPart"}

# A persistence-ready message row, still plaintext: (id, parent_id, seq, kind,
# text, blob). The drainer encrypts text + blob just before the write (lock-aware
# side of the queue), so a vault lock mid-turn parks the write rather than losing it.
_Row = tuple[str, str | None, int, str, str, str]


@dataclass
class _PersistJob:
    """A unit of durable work, drained in FIFO order so an active-leaf move or a
    delete always lands after the message writes it follows.

    - ``messages``: insert ``rows`` and set the active leaf (a completed turn).
    - ``active_leaf``: move the pointer only (regenerate/edit/rewind/switch).
    - ``delete``: remove ``deleted_ids`` (highest seq first, children before
      parents) and reseat the active leaf.
    """

    kind: str  # "messages" | "active_leaf" | "delete" | "pin"
    conversation_id: str
    active_leaf_id: str | None = None
    rows: list[_Row] = field(default_factory=list)
    deleted_ids: list[str] = field(default_factory=list)
    # For "pin": the message to (un)pin and the value to set.
    message_id: str | None = None
    pinned: bool = False


@dataclass
class _Node:
    """One message in the tree: a serialized-on-write ``ModelMessage`` plus the
    structural metadata that orders and links it."""

    id: str
    parent_id: str | None
    seq: int
    message: ModelMessage
    pinned: bool = False


class _Tree:
    """A conversation's message tree, held in memory while warm. Children lists are
    kept in ``seq`` (creation) order, which is the version order siblings render in."""

    def __init__(self) -> None:
        self.nodes: dict[str, _Node] = {}
        # parent_id -> child ids, seq-ascending. Roots sit under the None key.
        self.children: dict[str | None, list[str]] = {}
        self.active_leaf_id: str | None = None
        self.next_seq: int = 0

    def add(self, node: _Node) -> None:
        """Attach a node. Callers add in ascending ``seq`` (append assigns the next
        seq; rehydration feeds rows pre-sorted), so child lists stay seq-ordered."""
        self.nodes[node.id] = node
        self.children.setdefault(node.parent_id, []).append(node.id)
        self.next_seq = max(self.next_seq, node.seq + 1)

    def fallback_leaf(self) -> str | None:
        """The most-recently-created node, used when the stored active leaf is
        missing or dangling after a cold load."""
        if not self.nodes:
            return None
        return max(self.nodes.values(), key=lambda n: n.seq).id

    def active_path(self) -> list[_Node]:
        """The nodes from root to the active leaf, in order."""
        path: list[_Node] = []
        cur = self.active_leaf_id
        seen: set[str] = set()
        while cur is not None and cur not in seen:
            node = self.nodes.get(cur)
            if node is None:
                break
            seen.add(cur)
            path.append(node)
            cur = node.parent_id
        path.reverse()
        return path

    def append_chain(self, messages: list[ModelMessage]) -> list[_Node]:
        """Add ``messages`` as a chain hanging off the current active leaf, and
        advance the leaf to the chain's tip. New nodes branch automatically when
        the leaf already has children (a regenerate/edit having moved it back)."""
        added: list[_Node] = []
        parent = self.active_leaf_id
        for message in messages:
            node = _Node(id=new_id(), parent_id=parent, seq=self.next_seq, message=message)
            self.add(node)
            parent = node.id
            added.append(node)
        if added:
            self.active_leaf_id = added[-1].id
        return added

    def siblings(self, node_id: str) -> list[str]:
        """The version set ``node_id`` belongs to — its parent's children, in
        version (seq) order. Includes ``node_id`` itself."""
        node = self.nodes.get(node_id)
        if node is None:
            return []
        return self.children.get(node.parent_id, [])

    def descend_to_leaf(self, node_id: str) -> str:
        """Follow the most recent child at each step down to a leaf — the tip a
        branch resumes at when its version is selected."""
        cur = node_id
        seen: set[str] = set()
        while cur not in seen:
            seen.add(cur)
            kids = self.children.get(cur, [])
            if not kids:
                return cur
            cur = max(kids, key=lambda cid: self.nodes[cid].seq)
        return cur

    def subtree_ids(self, node_id: str) -> list[str]:
        """``node_id`` and all its descendants, highest seq first (children before
        parents — a safe delete order under self-referential foreign keys)."""
        out: list[str] = []
        stack = [node_id]
        while stack:
            cur = stack.pop()
            if cur in self.nodes and cur not in out:
                out.append(cur)
                stack.extend(self.children.get(cur, []))
        out.sort(key=lambda i: self.nodes[i].seq, reverse=True)
        return out

    def remove(self, ids: list[str]) -> None:
        """Drop the given nodes from the tree, detaching them from their parents."""
        doomed = set(ids)
        for node_id in ids:
            node = self.nodes.get(node_id)
            if node is not None and node.parent_id in self.children:
                self.children[node.parent_id] = [
                    c for c in self.children[node.parent_id] if c != node_id
                ]
            self.nodes.pop(node_id, None)
            self.children.pop(node_id, None)
        # Tidy any now-empty child buckets we left behind.
        for parent_id in list(self.children):
            if parent_id in doomed:
                self.children.pop(parent_id, None)


def _defer_fk(session: Session) -> None:
    """Defer foreign-key enforcement to commit for this transaction, so a set of
    rows linked by the self-referential ``parent_id`` FK can be deleted in one
    statement regardless of order. SQLite checks FKs per-statement otherwise; this
    is its mechanism (a no-op guard keeps a non-SQLite backend from erroring on the
    pragma — such a backend would use deferrable constraints instead)."""
    if session.bind is not None and session.bind.dialect.name == "sqlite":
        session.execute(sa_text("PRAGMA defer_foreign_keys=ON"))


def _is_user_prompt(message: ModelMessage) -> bool:
    """A request that carries an operator prompt — the boundary that starts a new
    turn (tool-return requests don't)."""
    return isinstance(message, ModelRequest) and any(
        isinstance(p, UserPromptPart) for p in message.parts
    )


@dataclass
class ConversationSummaryView:
    """A listing projection — never the authoritative history, just enough to
    render a sidebar row."""

    id: str
    title: str | None
    created_at: datetime
    updated_at: datetime
    message_count: int
    preview: str | None


def _project(message: ModelMessage) -> tuple[str, str]:
    """Derive (kind, text) for listing/search from a ModelMessage."""
    kind = getattr(message, "kind", "")
    text = " ".join(
        part.content
        for part in message.parts
        if type(part).__name__ in _TEXT_PARTS and isinstance(getattr(part, "content", None), str)
    )
    return kind, text


def _db_stats(
    session: Session, conversation_ids: list[str]
) -> dict[str, tuple[int, str | None]]:
    """(message_count, last-message text) per conversation, from the durable rows.

    One ``COUNT … GROUP BY`` for the counts and one max-seq lookup for the last
    text — no per-conversation row scan. Used only for **cold** conversations (no
    in-memory tree): the count is the total node count and the preview the latest
    by seq, which can include off-path branches; an active conversation overrides
    both from its tree (exact for the visible path). The returned text is still the
    encrypted ``Message.text`` ciphertext; the caller decrypts only what it renders."""
    if not conversation_ids:
        return {}
    counts = dict(
        session.exec(
            select(Message.conversation_id, func.count())
            .where(Message.conversation_id.in_(conversation_ids))
            .group_by(Message.conversation_id)
        ).all()
    )
    latest = (
        select(Message.conversation_id, func.max(Message.seq).label("seq"))
        .where(Message.conversation_id.in_(conversation_ids))
        .group_by(Message.conversation_id)
        .subquery()
    )
    last_text = dict(
        session.exec(
            select(Message.conversation_id, Message.text).join(
                latest,
                (Message.conversation_id == latest.c.conversation_id)
                & (Message.seq == latest.c.seq),
            )
        ).all()
    )
    return {cid: (counts.get(cid, 0), last_text.get(cid)) for cid in conversation_ids}


class ConversationStore:
    def __init__(self, engine: Engine, vault: Vault) -> None:
        self._engine = engine
        self._vault = vault
        self._cache: dict[str, _Tree] = {}
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
        self._cache[conversation_id] = _Tree()
        return conversation_id

    async def exists(self, conversation_id: str, owner_id: str) -> bool:
        """Whether ``conversation_id`` names a conversation owned by ``owner_id``."""
        def work(session: Session) -> bool:
            conversation = session.get(Conversation, conversation_id)
            return conversation is not None and conversation.owner_id == owner_id

        return await in_session(self._engine, work)

    async def _tree(self, conversation_id: str) -> _Tree:
        """The conversation's tree — from the cache, or rehydrated once from the DB."""
        cached = self._cache.get(conversation_id)
        if cached is not None:
            return cached

        # Serialize rehydration per conversation and re-check inside the lock, so a
        # concurrent record()/history() can't be clobbered by a stale DB snapshot.
        async with self._locks.setdefault(conversation_id, asyncio.Lock()):
            cached = self._cache.get(conversation_id)
            if cached is not None:
                return cached

            def work(
                session: Session,
            ) -> tuple[list[tuple[str, str | None, int, bool, str]], str | None]:
                rows = session.exec(
                    select(Message)
                    .where(Message.conversation_id == conversation_id)
                    .order_by(Message.seq)
                ).all()
                conversation = session.get(Conversation, conversation_id)
                active = conversation.active_leaf_id if conversation is not None else None
                return [(r.id, r.parent_id, r.seq, r.pinned, r.blob) for r in rows], active

            rows, active = await in_session(self._engine, work)
            tree = _Tree()
            for row_id, parent_id, seq, pinned, blob in rows:  # pre-sorted by seq
                message = _MESSAGE.validate_json(self._vault.decrypt_str(blob))
                tree.add(
                    _Node(
                        id=row_id,
                        parent_id=parent_id,
                        seq=seq,
                        message=message,
                        pinned=pinned,
                    )
                )
            tree.active_leaf_id = active if active in tree.nodes else tree.fallback_leaf()
            self._cache[conversation_id] = tree
            return tree

    async def history(self, conversation_id: str) -> list[ModelMessage]:
        """The active path's messages — the flat history the agent continues from."""
        tree = await self._tree(conversation_id)
        return [node.message for node in tree.active_path()]

    def _summarize(
        self, conversation: Conversation, db_count: int, last_text_enc: str | None
    ) -> ConversationSummaryView:
        """Build a listing summary, preferring the in-memory tree's active-path
        count + preview (exact for the visible thread, and ahead of the DB by the
        write-behind drainer) over the durable rows. Runs outside the DB session —
        only touches the vault + cache."""
        cached = self._cache.get(conversation.id)
        if cached is not None:
            path = cached.active_path()
            count = len(path)
            preview = next(
                (text for text in (_project(n.message)[1] for n in reversed(path)) if text), None
            )
        else:
            count = db_count
            decrypted = self._vault.decrypt_str(last_text_enc).strip() if last_text_enc else ""
            preview = decrypted or None
        return ConversationSummaryView(
            id=conversation.id,
            title=conversation.title,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            message_count=count,
            preview=preview[:140] if preview else None,
        )

    async def list_conversations(self, owner_id: str) -> list[ConversationSummaryView]:
        """Owner's conversations, newest-updated first, with a derived count +
        preview. The durable rows are the base; an active conversation's in-memory
        tree overrides count/preview so a just-sent turn shows immediately."""

        def work(session: Session) -> list[tuple[Conversation, int, str | None]]:
            conversations = session.exec(
                select(Conversation)
                .where(Conversation.owner_id == owner_id)
                .order_by(Conversation.updated_at.desc())
            ).all()
            stats = _db_stats(session, [c.id for c in conversations])
            return [(c, *stats.get(c.id, (0, None))) for c in conversations]

        rows = await in_session(self._engine, work)
        return [self._summarize(conv, count, last_enc) for conv, count, last_enc in rows]

    async def get_summary(
        self, conversation_id: str, owner_id: str
    ) -> ConversationSummaryView | None:
        """A single conversation's listing summary, or None if it isn't owned by
        ``owner_id``. Reads one thread's rows, not the whole corpus."""

        def work(session: Session) -> tuple[Conversation, int, str | None] | None:
            conversation = session.get(Conversation, conversation_id)
            if conversation is None or conversation.owner_id != owner_id:
                return None
            count, last_text_enc = _db_stats(session, [conversation_id])[conversation_id]
            return conversation, count, last_text_enc

        result = await in_session(self._engine, work)
        if result is None:
            return None
        return self._summarize(*result)

    async def messages_view(self, conversation_id: str) -> list[MessageView]:
        """The active path projected to render-ready user/assistant turns (reasoning
        split out, tool calls stitched to results), each carrying its branch node id
        and version index/count so the operator can regenerate, edit, or cycle it."""
        tree = await self._tree(conversation_id)
        nodes = tree.active_path()
        views = project_tree([(n.id, n.message) for n in nodes])
        for view in views:
            node = tree.nodes.get(view.id)
            if node is not None:
                view.pinned = node.pinned
            siblings = tree.siblings(view.id)
            if siblings:
                view.version_count = len(siblings)
                view.version_index = siblings.index(view.id) if view.id in siblings else 0
        return views

    async def set_title(self, conversation_id: str, title: str | None) -> None:
        """Rename a conversation (and bump its updated_at)."""

        def work(session: Session) -> None:
            conversation = session.get(Conversation, conversation_id)
            if conversation is not None:
                conversation.title = title
                conversation.updated_at = datetime.now(UTC)

        await in_session(self._engine, work)

    async def set_title_if_absent(self, conversation_id: str, title: str) -> bool:
        """Set the title only when the conversation has none yet; return whether it
        was applied. This is the authoritative "fill, don't overwrite" guard for
        auto-titling — it can never clobber a name the operator chose, and a caller
        only announces the title when this returns True. Atomic within one session
        (check-and-set), so it is safe against a concurrent rename."""

        def work(session: Session) -> bool:
            conversation = session.get(Conversation, conversation_id)
            if conversation is None or (conversation.title or "").strip():
                return False
            conversation.title = title
            conversation.updated_at = datetime.now(UTC)
            return True

        return await in_session(self._engine, work)

    async def delete_conversation(self, conversation_id: str) -> None:
        """Drop a conversation and its messages from the durable record, and evict
        the in-memory tree."""

        def work(session: Session) -> None:
            conversation = session.get(Conversation, conversation_id)
            # Defer FK checks so the whole message set drops in one statement,
            # without ordering children before parents for the self-referential FK.
            _defer_fk(session)
            session.execute(delete(Message).where(Message.conversation_id == conversation_id))
            if conversation is not None:
                session.delete(conversation)

        await in_session(self._engine, work)
        self._cache.pop(conversation_id, None)
        self._locks.pop(conversation_id, None)

    def record(self, conversation_id: str, new_messages: list[ModelMessage]) -> None:
        """Hot path: extend the tree off the active leaf and queue the durable write.

        Only projects and serializes here (no vault) — the drainer encrypts just
        before the write, on the lock-aware side of the queue. New messages branch
        automatically when a prior regenerate/edit moved the active leaf back."""
        if not new_messages:
            return
        tree = self._cache.setdefault(conversation_id, _Tree())
        added = tree.append_chain(new_messages)
        rows: list[_Row] = []
        for node in added:
            kind, text = _project(node.message)
            blob = _MESSAGE.dump_json(node.message).decode()
            rows.append((node.id, node.parent_id, node.seq, kind, text, blob))
        self._worker.submit(
            _PersistJob(
                kind="messages",
                conversation_id=conversation_id,
                active_leaf_id=tree.active_leaf_id,
                rows=rows,
            )
        )

    # ── Tree navigation (regenerate / edit / rewind / version switch / delete) ──
    #
    # Each moves the active leaf in memory (immediately authoritative) and queues
    # the matching durable update. Regenerate/edit only reposition the leaf — the
    # caller then launches a normal turn whose record() writes the new branch.

    def _move_leaf(self, conversation_id: str, leaf_id: str | None) -> None:
        """Queue an active-leaf move (the in-memory tree is already updated)."""
        self._worker.submit(
            _PersistJob(
                kind="active_leaf", conversation_id=conversation_id, active_leaf_id=leaf_id
            )
        )

    async def _reseat_to_parent(
        self, conversation_id: str, message_id: str, *, require_parent: bool
    ) -> bool:
        """Move the active leaf to ``message_id``'s parent, so the next turn branches
        in as a sibling of ``message_id``. ``require_parent`` rejects a root node
        (regenerate needs a preceding request; edit allows branching from the root).
        Returns False if the node is unknown (or rootless when required)."""
        tree = await self._tree(conversation_id)
        node = tree.nodes.get(message_id)
        if node is None or (require_parent and node.parent_id is None):
            return False
        tree.active_leaf_id = node.parent_id
        self._move_leaf(conversation_id, tree.active_leaf_id)
        return True

    async def regenerate_point(self, conversation_id: str, message_id: str) -> bool:
        """Set up a regenerate of the assistant turn whose branch node is
        ``message_id``: move the active leaf back to the user request that preceded
        it, so a fresh turn (run with no new prompt) records a sibling answer.
        Returns False if the node is unknown or has no preceding request."""
        return await self._reseat_to_parent(conversation_id, message_id, require_parent=True)

    async def edit_point(self, conversation_id: str, message_id: str) -> bool:
        """Set up an edit of the user turn whose request node is ``message_id``:
        move the active leaf to that request's parent, so a fresh turn (run with the
        edited prompt) records a sibling request + answer. Returns False if unknown."""
        return await self._reseat_to_parent(conversation_id, message_id, require_parent=False)

    async def switch_version(
        self, conversation_id: str, message_id: str, target_index: int
    ) -> bool:
        """Cycle the turn at ``message_id`` to version ``target_index`` among its
        siblings, descending that branch to its leaf. Returns False on a bad id or
        out-of-range index."""
        tree = await self._tree(conversation_id)
        if message_id not in tree.nodes:
            return False
        siblings = tree.siblings(message_id)
        if not 0 <= target_index < len(siblings):
            return False
        tree.active_leaf_id = tree.descend_to_leaf(siblings[target_index])
        self._move_leaf(conversation_id, tree.active_leaf_id)
        return True

    async def rewind(self, conversation_id: str, message_id: str) -> bool:
        """Rewind the active leaf to the tail of the turn whose branch node is
        ``message_id`` (on the current path), so the thread ends there and the next
        send branches. Returns False if the node isn't on the active path."""
        tree = await self._tree(conversation_id)
        path = tree.active_path()
        ids = [n.id for n in path]
        if message_id not in ids:
            return False
        idx = ids.index(message_id)
        # Extend to the tail of *this* turn: an assistant turn spans its response
        # plus interleaved tool-return requests up to the next user prompt. A user
        # turn is just its own request (its answer is the next turn), so don't
        # advance past it — the thread then ends at the user message as documented.
        if not _is_user_prompt(path[idx].message):
            while idx + 1 < len(path) and not _is_user_prompt(path[idx + 1].message):
                idx += 1
        tree.active_leaf_id = path[idx].id
        self._move_leaf(conversation_id, tree.active_leaf_id)
        return True

    async def set_pin(self, conversation_id: str, message_id: str, pinned: bool) -> bool:
        """Pin or unpin a turn (by its branch node id). Returns False if unknown.
        Queued behind any in-flight message writes so it lands on a persisted row."""
        tree = await self._tree(conversation_id)
        node = tree.nodes.get(message_id)
        if node is None:
            return False
        node.pinned = pinned
        self._worker.submit(
            _PersistJob(
                kind="pin",
                conversation_id=conversation_id,
                message_id=message_id,
                pinned=pinned,
            )
        )
        return True

    async def delete_message(self, conversation_id: str, message_id: str) -> bool:
        """Delete the turn whose branch node is ``message_id`` and everything after
        it on every branch (its subtree), reseating the active leaf on the parent if
        it fell inside. Returns False if the node is unknown."""
        tree = await self._tree(conversation_id)
        node = tree.nodes.get(message_id)
        if node is None:
            return False
        doomed = tree.subtree_ids(message_id)  # highest seq first
        new_leaf = tree.active_leaf_id
        if new_leaf is None or new_leaf in set(doomed):
            new_leaf = node.parent_id
        tree.remove(doomed)
        keep = new_leaf is None or new_leaf in tree.nodes
        tree.active_leaf_id = new_leaf if keep else tree.fallback_leaf()
        self._worker.submit(
            _PersistJob(
                kind="delete",
                conversation_id=conversation_id,
                active_leaf_id=tree.active_leaf_id,
                deleted_ids=doomed,
            )
        )
        return True

    # ── Write-behind drainer ───────────────────────────────────────────────────

    async def _persist(self, job: _PersistJob) -> None:
        if job.kind == "messages":
            await self._persist_messages(job)
        elif job.kind == "active_leaf":
            await self._persist_active_leaf(job)
        elif job.kind == "delete":
            await self._persist_delete(job)
        elif job.kind == "pin":
            await self._persist_pin(job)

    async def _persist_messages(self, job: _PersistJob) -> None:
        def work(session: Session) -> None:
            # The conversation may have been deleted while this write sat in the
            # queue — don't resurrect it as orphaned message rows.
            conversation = session.get(Conversation, job.conversation_id)
            if conversation is None:
                return
            for row_id, parent_id, seq, kind, text, blob in job.rows:
                session.add(
                    Message(
                        id=row_id,
                        conversation_id=job.conversation_id,
                        parent_id=parent_id,
                        seq=seq,
                        kind=kind,
                        text=self._vault.encrypt_str(text),
                        blob=self._vault.encrypt_str(blob),
                    )
                )
            conversation.active_leaf_id = job.active_leaf_id
            conversation.updated_at = datetime.now(UTC)

        await in_session(self._engine, work)

    async def _persist_active_leaf(self, job: _PersistJob) -> None:
        def work(session: Session) -> None:
            conversation = session.get(Conversation, job.conversation_id)
            if conversation is not None:
                conversation.active_leaf_id = job.active_leaf_id
                conversation.updated_at = datetime.now(UTC)

        await in_session(self._engine, work)

    async def _persist_delete(self, job: _PersistJob) -> None:
        def work(session: Session) -> None:
            conversation = session.get(Conversation, job.conversation_id)
            if conversation is None:
                return
            if job.deleted_ids:
                _defer_fk(session)  # remove the subtree in one statement, FK-safe
                session.execute(delete(Message).where(Message.id.in_(job.deleted_ids)))
            conversation.active_leaf_id = job.active_leaf_id
            conversation.updated_at = datetime.now(UTC)

        await in_session(self._engine, work)

    async def _persist_pin(self, job: _PersistJob) -> None:
        def work(session: Session) -> None:
            # Deliberately does not bump updated_at: pinning is a bookmark, not
            # activity, and must not float the conversation in the newest-first list.
            row = session.get(Message, job.message_id) if job.message_id else None
            if row is not None:
                row.pinned = job.pinned

        await in_session(self._engine, work)

    def _on_drop(self, job: _PersistJob, exc: Exception) -> None:
        logger.error(
            "permanently failed to persist %s for conversation %s (%d rows, %d deletes): %s",
            job.kind,
            job.conversation_id,
            len(job.rows),
            len(job.deleted_ids),
            exc,
        )
