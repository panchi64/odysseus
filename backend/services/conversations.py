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

The **title** is sealed too, but on the write path rather than in the drainer: it
is set by a rename or by auto-titling, both of which already run with the vault
unlocked, and neither rides the queue. It is user content — an auto-generated
summary of the operator's own first message, the most revealing single line a
thread has (`XC-SEC-3`). Rows written before it was sealed still carry the legacy
cleartext ``Conversation.title``; every read goes through ``_open_title``, which
prefers the ciphertext and falls back, and the startup backfill (``services/sealing``)
drains the cleartext away once the vault is unlocked.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, NamedTuple

from pydantic import TypeAdapter
from pydantic_ai import (
    BinaryContent,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    UserPromptPart,
)
from sqlalchemy import Engine, delete, func, or_
from sqlalchemy import text as sa_text
from sqlmodel import Session, select

from core.db import in_session
from core.exceptions import DegradedCapabilityError
from core.vault import Vault
from core.worker import WriteBehindWorker
from models._fields import new_id
from models.conversation import Conversation, Message
from runs.events import LastRequestUsage
from runs.overhead import TurnOverhead
from runs.timings import ResponseTiming, TimingTotals
from services.conversation_view import MessageView, project_tree
from services.embeddings import Embedder, embed_and_seal_rows, encode_vector
from services.modes import DEFAULT_MODE, ModeId, mode_spec
from services.permissions import DEFAULT_PERMISSION, PermissionLevel, permission_level
from services.projects import project_clause
from services.sealing import open_sealed

logger = logging.getLogger(__name__)

# How many conversation trees stay decrypted in memory. Sized for one operator: the
# working set is the handful of threads actually being read or written, and a miss
# costs one rehydrate from the database, not an error.
_DEFAULT_MAX_CACHED_CONVERSATIONS = 64

_MESSAGE = TypeAdapter(ModelMessage)
_TEXT_PARTS = {"TextPart", "UserPromptPart", "SystemPromptPart"}


class _Row(NamedTuple):
    """A persistence-ready message row, still plaintext. The drainer encrypts ``text`` +
    ``blob`` just before the write (lock-aware side of the queue), so a vault lock
    mid-turn parks the write rather than losing it."""

    id: str
    parent_id: str | None
    seq: int
    kind: str
    text: str
    blob: str
    attachment_ids: list[str]
    blocked_reason: str | None
    # Set only on a conversation-compaction checkpoint: the flag, plus the id of the last
    # node on the path its summary covers. See `record_compaction`.
    compacted: bool = False
    compacted_through: str | None = None
    # Wall-clock for a model response, from the run's own stopwatch. Null on requests.
    llm_ms: int | None = None
    ttft_ms: int | None = None
    tool_ms: int | None = None


class _HydratedRow(NamedTuple):
    """One message row read back for rehydration, projected out of the ORM object so
    nothing is held across the session boundary.

    Named rather than a bare tuple: it is unpacked positionally at the far end of the
    read, and a plain 12-tuple makes adding a column a silent off-by-one that lands as
    a wrong *value* in a neighbouring field rather than an error."""

    id: str
    parent_id: str | None
    seq: int
    pinned: bool
    blob: str
    attachment_ids: list[str]
    blocked_reason: str | None
    compacted: bool
    compacted_through: str | None
    llm_ms: int | None
    ttft_ms: int | None
    tool_ms: int | None


@dataclass
class _PersistJob:
    """A unit of durable work, drained in FIFO order so an active-leaf move or a
    delete always lands after the message writes it follows.

    - ``messages``: insert ``rows`` and set the active leaf (a completed turn).
    - ``active_leaf``: move the pointer only (regenerate/edit/rewind/switch).
    - ``delete``: remove ``deleted_ids`` (highest seq first, children before
      parents) and reseat the active leaf.
    """

    kind: str  # "messages" | "active_leaf" | "delete" | "pin" | "unblock"
    conversation_id: str
    active_leaf_id: str | None = None
    rows: list[_Row] = field(default_factory=list)
    deleted_ids: list[str] = field(default_factory=list)
    # For "pin": the message to (un)pin and the value to set. "unblock" reuses
    # ``message_id`` — the turn whose stop marker the operator resolved.
    message_id: str | None = None
    pinned: bool = False
    # The active path's last-used model at queue time — written denormalized onto
    # the Conversation alongside its active_leaf_id, so the listing reads it without
    # opening a blob. Computed where the leaf moves, never in the drainer (the tree
    # may have moved on by then). Unused by the "pin" job, which leaves model alone.
    model: str | None = None


@dataclass
class _Node:
    """One message in the tree: a serialized-on-write ``ModelMessage`` plus the
    structural metadata that orders and links it."""

    id: str
    parent_id: str | None
    seq: int
    message: ModelMessage
    pinned: bool = False
    # Upload ids the operator attached to this turn (a user request). Held alongside the
    # message so the conversation detail can render attachment chips without re-reading the
    # row; the message blob itself carries only the marker, never the file content.
    attachment_ids: list[str] = field(default_factory=list)
    # Set on an assistant turn's first response node when the run that produced it
    # ended blocked — the human-readable reason. None otherwise.
    blocked_reason: str | None = None
    # What this response cost in wall-clock (see `models.conversation.Message`). Held on
    # the node so a warm thread reports the same totals as a cold one — the in-memory
    # tree is authoritative until the drainer catches up, so timings that lived only in
    # the queued row would vanish from the readout for the rest of the session.
    llm_ms: int | None = None
    ttft_ms: int | None = None
    tool_ms: int | None = None
    # A conversation-compaction checkpoint (see `record_compaction`): this node's message
    # is a utility-model summary of everything on the path up to and including
    # `compacted_through`. The summarized nodes stay in the tree untouched — only what the
    # *model* replays changes (`model_history`).
    compacted: bool = False
    compacted_through: str | None = None


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


def _is_turn_start(path: list[_Node], index: int) -> bool:
    """Whether ``path[index]`` opens a fresh operator turn — a user-prompt request that is
    either the conversation's root or directly follows an assistant response.

    Not every user-prompt request opens a turn. A message the operator sends *while a run
    is executing* is persisted as its own request sitting directly behind the tool-return
    request it was injected into (the engine's injected-request split), so counting bare
    user prompts would read a mid-run aside as a whole exchange — and a compaction that
    keeps "the last two turns" would keep two asides and fold a real one."""
    if not _is_user_prompt(path[index].message):
        return False
    return index == 0 or isinstance(path[index - 1].message, ModelResponse)


def _checkpoint_split(path: list[_Node]) -> tuple[int, int]:
    """``(checkpoint, through)`` — the path index of the newest compaction checkpoint and
    the index of the last node its summary covers. ``(-1, -1)`` when the path holds no
    checkpoint. A checkpoint whose covered node is no longer on the path degrades to
    ``through == checkpoint``: the summary still stands, it just covers nothing verbatim."""
    checkpoint = next((i for i in range(len(path) - 1, -1, -1) if path[i].compacted), -1)
    if checkpoint < 0:
        return -1, -1
    through_id = path[checkpoint].compacted_through
    through = next((i for i, node in enumerate(path) if node.id == through_id), checkpoint)
    return checkpoint, through


def _replay_nodes(path: list[_Node], stop: int | None = None) -> list[_Node]:
    """The nodes the **model** replays: the newest checkpoint's summary **hoisted to the
    front**, then every node after the one it covers. ``stop`` truncates at a path index,
    which is how a fresh compaction collects exactly what it is about to fold.

    Hoisting is what lets the checkpoint be a plain leaf node in the tree. Splicing it in
    at the boundary instead would mean re-parenting a live node, which would pull the
    turns below it out of their own version sets. Hoisting also preserves the regenerate
    shape: with the leaf reseated onto a user request, the replay still *ends* on that
    request even though the checkpoint was appended after it."""
    end = len(path) if stop is None else stop
    checkpoint, through = _checkpoint_split(path)
    if checkpoint < 0:
        return path[:end]
    head = [path[checkpoint]] if checkpoint < end else []
    return head + [path[i] for i in range(through + 1, end) if i != checkpoint]


def _view_nodes(path: list[_Node]) -> list[_Node]:
    """The nodes the **operator** sees, in transcript order: each compaction checkpoint
    moved back to sit immediately after the node its summary covers.

    The opposite reordering to :func:`_replay_nodes`, and deliberately so. The model wants
    the summary first, as a preamble; the operator wants it where it happened, so the
    divider reads "everything above this line is what got folded" rather than trailing the
    recent turns it did *not* fold. A checkpoint whose covered node has left the path stays
    where it is rather than disappearing."""
    followers: dict[str, list[_Node]] = {}
    for node in path:
        if node.compacted and node.compacted_through:
            followers.setdefault(node.compacted_through, []).append(node)
    if not followers:
        return path
    on_path = {node.id for node in path}
    out: list[_Node] = []
    for node in path:
        if node.compacted and node.compacted_through in on_path:
            continue  # emitted after its anchor below
        out.append(node)
        out.extend(followers.get(node.id, ()))
    return out


def _turn_anchor_id(path: list[_Node], node_id: str) -> str | None:
    """The id of the **rendered turn** ``node_id`` belongs to — a turn's branch node, the
    same one ``project_tree`` keys a view by: the user request for an operator turn, the
    first response for an assistant one.

    A tree node is not a rendered message: an assistant turn spans several nodes and shows
    as one bubble. A live client is told where to draw the divider in terms it can actually
    address, so the position it draws matches the one a reload computes rather than
    approximating it."""
    index = next((i for i, node in enumerate(path) if node.id == node_id), None)
    if index is None:
        return None
    if _is_user_prompt(path[index].message):
        return path[index].id
    start = max((j for j in range(index + 1) if _is_turn_start(path, j)), default=None)
    if start is None:
        return path[index].id
    first_response = next(
        (path[j].id for j in range(start, index + 1) if isinstance(path[j].message, ModelResponse)),
        None,
    )
    return first_response or path[index].id


#: How long a forked thread's title may run before it is cut. The source's title is
#: already a short summary, so this only bites on a hand-typed rename.
_FORK_TITLE_MAX = 80


def _forked_title(source: str | None) -> str | None:
    """The new thread's name. Prefixed rather than auto-titled: the operator forked a
    *specific* conversation and the listing should say which, and a fork whose first
    action is a fresh model call to name itself would spend a request restating what the
    source already said."""
    if not source or not source.strip():
        return None
    trimmed = source.strip()[:_FORK_TITLE_MAX]
    return f"Fork of {trimmed}"


@dataclass(frozen=True)
class ConversationBinding:
    """How a thread works: where its file work happens, and how far the model may go on
    its own.

    Read as one record because the parts are only meaningful together — a worktree mode
    with no project and a project with no worktree mode are both nonsense and both
    silently plausible if the two are fetched separately, and a run that resolved its
    workspace from the conversation but its permission level from somewhere else would be
    two threads wearing one name.
    """

    mode: ModeId = DEFAULT_MODE
    project_id: str | None = None
    permission: PermissionLevel = DEFAULT_PERMISSION


@dataclass(frozen=True)
class CompactionPlan:
    """What one conversation compaction would fold, resolved against the active path.

    ``messages`` is the model's *current* replay view up to the boundary — so a second
    compaction summarizes the first summary plus what followed it, never the original
    turns all over again. ``expected_leaf_id`` is re-checked at record time, because
    generating the summary takes seconds and the operator can switch versions meanwhile."""

    messages: list[ModelMessage]
    through_id: str
    expected_leaf_id: str
    # The rendered turn the divider follows — what a live client needs to place it where a
    # reload will, since it addresses turns, not tree nodes. None when the covered node
    # doesn't resolve to a turn (defensive; the client then appends).
    anchor_id: str | None


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
    # The model the conversation last ran on (the most recent response's
    # model_name). None for a conversation with no answer yet.
    model: str | None = None
    # What kind of work this thread is, normalised through the mode registry. On the
    # *listing* projection and not only the detail, because the sidebar's shape depends
    # on it: the rail shows one mode at a time and groups code threads by the directory
    # they work in, neither of which it can do by opening every thread.
    mode: str = DEFAULT_MODE
    # The project a code thread works in, or None for an unfiled thread. The id, not the
    # path — the route resolves it to a directory basename, which is the only part of a
    # host path a listing should ever carry.
    project_id: str | None = None


def _model_of(message: ModelMessage) -> str | None:
    """The model that produced a response message, or None for a request."""
    return getattr(message, "model_name", None) if isinstance(message, ModelResponse) else None


def _active_path_model(path: list[_Node]) -> str | None:
    """The model the active path last ran on — its most recent response's
    ``model_name``. None for a path with no answer yet."""
    return next((m for m in (_model_of(n.message) for n in reversed(path)) if m), None)


def context_footprint(messages: list[ModelMessage]) -> int | None:
    """The context footprint after a turn: the most recent model response's prompt
    plus its generation — the tokens the next turn carries forward. None when there
    is no response, or the provider reported no usage (local servers often leave
    ``input_tokens`` at 0, which we can't tell from real and so treat as unmeasured
    rather than render a misleading 0%). Shared by the live run metrics and the
    cold-load conversation detail so both report the same quantity."""
    for message in reversed(messages):
        if isinstance(message, ModelResponse):
            usage = message.usage
            return usage.input_tokens + (usage.output_tokens or 0) if usage.input_tokens else None
    return None


def last_request_usage(messages: list[ModelMessage]) -> LastRequestUsage | None:
    """The most recent model response's own figures — the route it took and what the
    provider's cache did with its prompt.

    The same backwards walk :func:`context_footprint` makes, over the same list, for the
    same reason: everything else the readout reports is cumulative over the path, and
    these two are properties of one request. A fallback chain's second model and a cold
    cache both vanish into a running total, which is precisely when an operator wants to
    know about them.

    None when the path holds no response at all. A response that reported no usage still
    answers with its route, since which model spoke is known whether or not it said what
    that cost — and every token field stays null rather than zero, matching the frame it
    rides on."""
    for message in reversed(messages):
        if not isinstance(message, ModelResponse):
            continue
        usage = message.usage
        provider = getattr(message, "provider_name", None)
        model = getattr(message, "model_name", None)
        return LastRequestUsage(
            route=f"{provider}:{model}" if provider and model else model,
            # Zero is what a local server reports when it means "not measured", which is
            # indistinguishable from a real zero and so is treated as absent here exactly
            # as it is in `context_footprint` above.
            input_tokens=usage.input_tokens or None,
            output_tokens=usage.output_tokens or None,
            cache_read_tokens=usage.cache_read_tokens or None,
            cache_write_tokens=usage.cache_write_tokens or None,
        )
    return None


@dataclass(frozen=True, slots=True)
class ConversationTotals:
    """What a thread has cost, counted off its **active path**.

    Derived from the messages themselves, never from a running counter, and that is
    the whole design. The conversation is a *tree*: a rewind or a version switch moves
    the active leaf, and a stored total would go on reporting tokens spent down a
    branch the operator has walked away from. Counting the path each time means the
    numbers follow navigation for free, and a cold load and a live turn compute the
    same figure from the same function.

    Token fields are None when nothing reported them, matching ``context_footprint``:
    local servers routinely leave ``input_tokens`` at 0, which is indistinguishable
    from a real zero, so an unmeasured thread reports absent rather than free.
    """

    #: Completed operator exchanges (see ``_is_user_prompt``/turn-start semantics).
    turns: int = 0
    #: Model round-trips those turns took between them.
    steps: int = 0
    tool_calls: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    #: Provider-reported cached prompt tokens. None when no response reported any —
    #: most OpenAI-compatible and local endpoints never do.
    cache_read_tokens: int | None = None


def conversation_totals(messages: list[ModelMessage]) -> ConversationTotals:
    """Sum a message path into the readout's counts.

    ``steps`` counts model responses and ``turns`` counts the operator's own prompts
    that open an exchange — the same distinction ``_is_turn_start`` draws, applied to a
    flat message list: a prompt directly following another request is a mid-run aside
    the operator sent while the model worked, not a new exchange."""
    turns = steps = tool_calls = 0
    input_tokens = output_tokens = cache_read = 0
    saw_tokens = saw_cache = False
    previous: ModelMessage | None = None

    for message in messages:
        if isinstance(message, ModelResponse):
            steps += 1
            tool_calls += sum(1 for p in message.parts if isinstance(p, ToolCallPart))
            usage = message.usage
            if usage.input_tokens:
                saw_tokens = True
                input_tokens += usage.input_tokens
                output_tokens += usage.output_tokens or 0
            # Distinguished from "cached nothing": a provider that reports the field at
            # all is taken at its word, including when it says zero.
            if usage.cache_read_tokens:
                saw_cache = True
                cache_read += usage.cache_read_tokens
        elif _is_user_prompt(message) and (previous is None or isinstance(previous, ModelResponse)):
            turns += 1
        previous = message

    return ConversationTotals(
        turns=turns,
        steps=steps,
        tool_calls=tool_calls,
        input_tokens=input_tokens if saw_tokens else None,
        output_tokens=output_tokens if saw_tokens else None,
        cache_read_tokens=cache_read if saw_cache else None,
    )


def _part_text(content: object) -> str:
    """Searchable text from a message part's content — a bare string, or the string
    items of a multimodal list (a user prompt that retains an attachment inline, where
    content is ``[prompt, BinaryContent | str, …]``), ignoring binary parts."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(item for item in content if isinstance(item, str))
    return ""


def _project(message: ModelMessage) -> tuple[str, str]:
    """Derive (kind, text) for listing/search from a ModelMessage. Flattens a
    retained-attachment user prompt (list content) so its text still feeds the
    listing preview and the per-message embedding — a string-only check would drop it."""
    kind = getattr(message, "kind", "")
    pieces = (
        _part_text(part.content) for part in message.parts if type(part).__name__ in _TEXT_PARTS
    )
    return kind, " ".join(p for p in pieces if p)


def _prompt_text(content: object) -> str:
    """The operator's typed text from a user-prompt content value. The engine builds an
    attachment turn's content as ``[prompt, *attachment_parts]``, so the leading string is
    the prompt; a bare string is already it. Deliberately *not* a join (unlike ``_project``
    / ``conversation_view.flatten_content``) — a join would also slurp the injected file text
    this strip exists to drop."""
    if isinstance(content, str):
        return content
    if isinstance(content, list) and content and isinstance(content[0], str):
        return content[0]
    return ""


def install_persisted_attachments(message: ModelMessage, persisted: list | None) -> None:
    """Replace a user request's *live* attachment content with the durable ``persisted``
    parts (the engine's capped set: images + under-cap text inline, larger text cut to a
    pointer, a closing id marker), keeping the operator's typed prompt — so replayed
    history carries the capped content, never the uncapped live payload. Collapses to a
    single string when nothing binary survives (a text-only turn persists exactly like a
    plain string), else keeps the multimodal list (a retained image stays inline). Owned
    by the store because *what gets persisted* is the store's concern; ``record`` applies
    it as it serializes. ``None`` (no seam) and a non-request message are no-ops; an
    **empty list is deliberate** — it strips the request back to the typed prompt alone,
    which is how the engine keeps its per-turn appended prompt context (the document
    state) out of the durable history on a turn with no attachments."""
    if persisted is None or not isinstance(message, ModelRequest):
        return
    for part in message.parts:
        if isinstance(part, UserPromptPart):
            prompt = _prompt_text(part.content)
            items: list = ([prompt] if prompt else []) + list(persisted)
            if any(isinstance(item, BinaryContent) for item in items):
                part.content = items
            else:
                part.content = "\n\n".join(item for item in items if isinstance(item, str)).strip()
            return  # one user-prompt part per request carries the attachments


def _db_stats(session: Session, conversation_ids: list[str]) -> dict[str, tuple[int, str | None]]:
    """(message_count, last-message text) per conversation, from the durable rows.

    One ``COUNT … GROUP BY`` for the counts and one max-seq lookup for the last
    text — no per-conversation row scan. Used only for **cold** conversations (no
    in-memory tree): the count is the total node count and the preview the latest
    by seq, which can include off-path branches; an active conversation overrides
    both from its tree (exact for the visible path). The returned text is still the
    encrypted ``Message.text`` ciphertext; the caller decrypts only what it renders.
    The last-used model isn't derived here — it rides denormalized on the
    ``Conversation`` row (kept in step with the active leaf), so listing never has
    to open a message blob."""
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
    def __init__(
        self,
        engine: Engine,
        vault: Vault,
        embedder: Embedder | None = None,
        *,
        max_cached_conversations: int = _DEFAULT_MAX_CACHED_CONVERSATIONS,
    ) -> None:
        self._engine = engine
        self._vault = vault
        # Embeds each persisted turn's text for cross-chat semantic search. Optional
        # (and best-effort): with no embedder, or when it degrades, messages persist
        # without a vector and recall over them falls back to keyword (EMB-2).
        self._embedder = embedder
        # Least-recently-used first. Every entry holds a fully *decrypted* tree —
        # including any inline image bytes a turn carried — so an unbounded dict grows
        # to the size of every conversation the process has ever touched and never
        # gives it back. It is a pure cache (`_tree` rehydrates on a miss), so evicting
        # costs one reload and nothing else.
        self._cache: OrderedDict[str, _Tree] = OrderedDict()
        self._max_cached = max_cached_conversations
        # Conversations with durable work still queued. `record()` extends the cached
        # tree in place and hands the drainer a *slice*, so evicting between the two
        # would leave `setdefault` rebuilding an empty tree and the turn appending to
        # nothing. Never evict one of these; the count drains to zero as the writes land.
        self._pending: Counter[str] = Counter()
        # conversation id → owner. Immutable per conversation, so it is memoized rather
        # than re-read on the write-behind path once per persisted turn.
        self._owners: dict[str, str] = {}
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

    # --- cache residency -----------------------------------------------------------
    def _cache_put(self, conversation_id: str, tree: _Tree) -> _Tree:
        """Install a tree as the most-recently-used entry and trim back to the cap."""
        self._cache[conversation_id] = tree
        self._cache.move_to_end(conversation_id)
        self._trim_cache()
        return tree

    def _cache_get(self, conversation_id: str) -> _Tree | None:
        """The cached tree, counting the read as a use so it isn't evicted next.

        Only genuine reads go through here. The listing summary and the compaction
        leaf check peek with a plain ``self._cache.get`` on purpose: the listing walks
        *every* conversation, so promoting each would flatten the ordering into
        meaninglessness and could evict the thread actually being used.
        """
        tree = self._cache.get(conversation_id)
        if tree is not None:
            self._cache.move_to_end(conversation_id)
        return tree

    def _trim_cache(self) -> None:
        """Drop least-recently-used trees until the cache is back within its cap.

        Entries with queued durable work are skipped, never dropped: `record()` mutates
        the cached tree and queues only the new slice, so evicting one mid-turn would
        leave the next `record` appending to a freshly-built empty tree. If every entry
        is pending — far more in flight than the cap — the cache simply runs over rather
        than corrupting a tree; the overflow drains on its own as the writes land.
        """
        if len(self._cache) <= self._max_cached:
            return
        for conversation_id in list(self._cache):
            if len(self._cache) <= self._max_cached:
                break
            if self._pending[conversation_id]:
                continue
            # A held lock means a rehydrate is in flight for this id. Dropping the lock
            # under it would let a second rehydrate run concurrently and clobber the
            # tree the first one is about to install.
            lock = self._locks.get(conversation_id)
            if lock is not None and lock.locked():
                continue
            del self._cache[conversation_id]
            self._locks.pop(conversation_id, None)

    async def create_conversation(
        self,
        owner_id: str,
        title: str | None = None,
        ephemeral: bool = False,
        *,
        project_id: str | None = None,
        mode: str = DEFAULT_MODE,
        permission: str | None = None,
    ) -> str:
        """Start a thread. ``project_id`` files it (null is unfiled, which is visible
        under every scope) and ``mode`` decides where its file work happens; both are
        set here and never afterwards — see `models/conversation.py`.

        ``permission`` is the level it *starts* at and moves freely afterwards; absent, the
        mode's own default applies, which is how a mode gets to say what a fresh thread in
        it should be allowed to do without every caller repeating the answer."""
        spec = mode_spec(mode)

        def work(session: Session) -> str:
            conversation = Conversation(
                owner_id=owner_id,
                title_enc=self._seal_title(title),
                ephemeral=ephemeral,
                project_id=project_id,
                mode=mode,
                permission_level=(
                    spec.default_permission if permission is None else permission_level(permission)
                ),
            )
            session.add(conversation)
            session.flush()
            return conversation.id

        conversation_id = await in_session(self._engine, work)
        self._cache_put(conversation_id, _Tree())
        self._owners[conversation_id] = owner_id
        return conversation_id

    async def exists(self, conversation_id: str, owner_id: str) -> bool:
        """Whether ``conversation_id`` names a conversation owned by ``owner_id``."""

        def work(session: Session) -> bool:
            conversation = session.get(Conversation, conversation_id)
            return conversation is not None and conversation.owner_id == owner_id

        return await in_session(self._engine, work)

    async def _tree(self, conversation_id: str) -> _Tree:
        """The conversation's tree — from the cache, or rehydrated once from the DB."""
        cached = self._cache_get(conversation_id)
        if cached is not None:
            return cached

        # Serialize rehydration per conversation and re-check inside the lock, so a
        # concurrent record()/history() can't be clobbered by a stale DB snapshot.
        async with self._locks.setdefault(conversation_id, asyncio.Lock()):
            cached = self._cache_get(conversation_id)
            if cached is not None:
                return cached

            def work(session: Session) -> tuple[list[_HydratedRow], str | None]:
                rows = session.exec(
                    select(Message)
                    .where(Message.conversation_id == conversation_id)
                    .order_by(Message.seq)
                ).all()
                conversation = session.get(Conversation, conversation_id)
                active = conversation.active_leaf_id if conversation is not None else None
                return [
                    _HydratedRow(
                        id=r.id,
                        parent_id=r.parent_id,
                        seq=r.seq,
                        pinned=r.pinned,
                        blob=r.blob,
                        attachment_ids=r.attachment_ids,
                        blocked_reason=r.blocked_reason,
                        compacted=r.compacted,
                        compacted_through=r.compacted_through,
                        llm_ms=r.llm_ms,
                        ttft_ms=r.ttft_ms,
                        tool_ms=r.tool_ms,
                    )
                    for r in rows
                ], active

            rows, active = await in_session(self._engine, work)
            tree = _Tree()
            for row in rows:  # pre-sorted by seq
                message = _MESSAGE.validate_json(self._vault.decrypt_str(row.blob))
                tree.add(
                    _Node(
                        id=row.id,
                        parent_id=row.parent_id,
                        seq=row.seq,
                        message=message,
                        pinned=row.pinned,
                        attachment_ids=row.attachment_ids,
                        blocked_reason=row.blocked_reason,
                        compacted=row.compacted,
                        compacted_through=row.compacted_through,
                        llm_ms=row.llm_ms,
                        ttft_ms=row.ttft_ms,
                        tool_ms=row.tool_ms,
                    )
                )
            tree.active_leaf_id = active if active in tree.nodes else tree.fallback_leaf()
            return self._cache_put(conversation_id, tree)

    async def history(self, conversation_id: str) -> list[ModelMessage]:
        """The active path's messages — the full transcript, compaction and all.

        This is what the operator's own surfaces read (titling, retitling, the context
        meter). The **model's** view is :meth:`model_history`, which is narrower once a
        thread has been compacted; the two are deliberately separate methods rather than
        one with a flag, because every caller here wants the whole thread."""
        tree = await self._tree(conversation_id)
        return [node.message for node in tree.active_path()]

    async def timings(self, conversation_id: str) -> TimingTotals:
        """The active path's wall-clock, summed — the one figure in the readout that
        can't be recovered from the messages themselves.

        Walks the same active path :meth:`history` does, so time follows a rewind or a
        version switch exactly as the token counts beside it do. Responses recorded
        before timings existed (or by a run whose stopwatch never reached them) carry
        null and contribute nothing, which is why a thread can honestly report tokens
        it can't report a duration for."""
        tree = await self._tree(conversation_id)
        nodes = tree.active_path()
        ttft = [n.ttft_ms for n in nodes if n.ttft_ms is not None]
        return TimingTotals(
            llm_ms=sum(n.llm_ms or 0 for n in nodes),
            tool_ms=sum(n.tool_ms or 0 for n in nodes),
            ttft_ms_total=sum(ttft),
            ttft_samples=len(ttft),
        )

    async def model_history(self, conversation_id: str) -> list[ModelMessage]:
        """The history the **model** replays: identical to :meth:`history` until the
        thread has been compacted, then the newest checkpoint's summary followed by the
        turns it doesn't cover. Nothing is lost — the folded turns stay in the tree and in
        the transcript; only what is re-sent each turn shrinks."""
        tree = await self._tree(conversation_id)
        return [node.message for node in _replay_nodes(tree.active_path())]

    async def compaction_plan(
        self, conversation_id: str, *, keep_turns: int
    ) -> CompactionPlan | None:
        """What compacting this conversation right now would fold, or ``None`` when it
        would fold nothing.

        The boundary is the ``keep_turns``-th-from-last turn start **after the newest
        existing checkpoint**, so a compaction can never reach back past an earlier one and
        re-expose its summary as an ordinary turn. Cutting at a turn start is also what
        keeps the retained tail replayable: a turn always opens with an operator prompt, so
        the split can't strand an assistant tool call from its result.

        ``None`` when the active leaf already has children — a regenerate or edit has
        reseated the leaf and its run hasn't recorded yet, and grafting a checkpoint there
        would re-parent the incoming answer out of the version set it belongs to. After any
        completed turn the leaf is childless again, so this only sits out the turn itself."""
        tree = await self._tree(conversation_id)
        leaf = tree.active_leaf_id
        if leaf is None or tree.children.get(leaf):
            return None
        path = tree.active_path()
        checkpoint, _ = _checkpoint_split(path)
        starts = [i for i in range(checkpoint + 1, len(path)) if _is_turn_start(path, i)]
        if len(starts) <= keep_turns:
            return None
        boundary = starts[-keep_turns] if keep_turns > 0 else len(path)
        folded = _replay_nodes(path, stop=boundary)
        if not folded:
            return None
        through_id = path[boundary - 1].id
        return CompactionPlan(
            messages=[node.message for node in folded],
            through_id=through_id,
            expected_leaf_id=leaf,
            anchor_id=_turn_anchor_id(path, through_id),
        )

    def record_compaction(
        self, conversation_id: str, *, summary: str, through_id: str, expected_leaf_id: str
    ) -> str | None:
        """Append a compaction checkpoint at the tip and queue its durable write, returning
        the new node's id — or ``None`` when the plan went stale.

        Synchronous on purpose, exactly like :meth:`record`: the staleness re-check and the
        append happen with no ``await`` between them, so under single-threaded asyncio no
        other coroutine can move the leaf in the window. It has to be re-checked at all
        because generating the summary takes seconds, and the route's conversation claim
        blocks *runs* — not a version switch or a rewind."""
        tree = self._cache.get(conversation_id)
        if tree is None or tree.active_leaf_id != expected_leaf_id:
            return None
        if tree.children.get(expected_leaf_id):
            return None
        message = ModelRequest(parts=[UserPromptPart(content=summary)])
        node = tree.append_chain([message])[0]
        node.compacted = True
        node.compacted_through = through_id
        self._submit(
            _PersistJob(
                kind="messages",
                conversation_id=conversation_id,
                active_leaf_id=tree.active_leaf_id,
                rows=[
                    _Row(
                        id=node.id,
                        parent_id=node.parent_id,
                        seq=node.seq,
                        kind="request",
                        # An empty projection, deliberately: a checkpoint contributes no
                        # embedding (the drainer only embeds non-empty text), no cross-chat
                        # search hit, and no listing preview. A summary surfacing in search
                        # as if it were the operator's own words is worse than not
                        # surfacing at all. The text lives only in the sealed blob.
                        text="",
                        blob=_MESSAGE.dump_json(message).decode(),
                        attachment_ids=[],
                        blocked_reason=None,
                        compacted=True,
                        compacted_through=through_id,
                    )
                ],
                model=_active_path_model(tree.active_path()),
            )
        )
        return node.id

    def _summarize(
        self, conversation: Conversation, db_count: int, last_text_enc: str | None
    ) -> ConversationSummaryView:
        """Build a listing summary, preferring the in-memory tree's active-path
        count + preview + model (exact for the visible thread, and ahead of the DB
        by the write-behind drainer) over the durable rows. Runs outside the DB
        session — only touches the vault + cache. The cold model comes from the
        denormalized ``Conversation.model``, kept in step with the active leaf, so
        warm and cold agree and listing never opens a blob."""
        cached = self._cache.get(conversation.id)
        if cached is not None:
            # Compaction checkpoints are chassis bookkeeping, not turns: they must not be
            # counted as messages, and the newest one must not become the listing preview
            # (it is the tip right after a compaction, so it otherwise would).
            path = [node for node in cached.active_path() if not node.compacted]
            count = len(path)
            preview = next(
                (text for text in (_project(n.message)[1] for n in reversed(path)) if text), None
            )
            model = _active_path_model(path)
        else:
            count = db_count
            decrypted = self._vault.decrypt_str(last_text_enc).strip() if last_text_enc else ""
            preview = decrypted or None
            model = conversation.model
        return ConversationSummaryView(
            id=conversation.id,
            title=self._open_title(conversation),
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            message_count=count,
            preview=preview[:140] if preview else None,
            model=model,
            # Normalised through the registry for the same reason `binding` does it: the
            # column is a plain string, and a listing that grouped rows under a mode this
            # build has no rule for would show the operator a section they cannot reach.
            mode=mode_spec(conversation.mode).id,
            project_id=conversation.project_id,
        )

    async def list_conversations(
        self,
        owner_id: str,
        *,
        visible_projects: tuple[str | None, ...] | None = None,
    ) -> list[ConversationSummaryView]:
        """Owner's conversations, newest-updated first, with a derived count +
        preview. The durable rows are the base; an active conversation's in-memory
        tree overrides count/preview so a just-sent turn shows immediately.

        ``visible_projects`` is the project scope (``services.projects``); ``None`` — the
        default — means no filtering, which is what every non-route caller wants."""

        def work(session: Session) -> list[tuple[Conversation, int, str | None]]:
            query = (
                select(Conversation)
                .where(Conversation.owner_id == owner_id)
                .where(Conversation.ephemeral == False)  # noqa: E712 — SQL boolean compare
            )
            scope = project_clause(Conversation.project_id, visible_projects)
            if scope is not None:
                query = query.where(scope)
            conversations = session.exec(query.order_by(Conversation.updated_at.desc())).all()
            stats = _db_stats(session, [c.id for c in conversations])
            return [(c, *stats.get(c.id, (0, None))) for c in conversations]

        rows = await in_session(self._engine, work)
        return [self._summarize(*row) for row in rows]

    async def count_conversations(self, owner_id: str) -> int:
        """How many conversations the owner has — a scalar count that loads no
        rows or previews (the overview readout, not the listing). Conversations
        are persisted on creation, so this is accurate the moment a turn starts."""

        def work(session: Session) -> int:
            return session.exec(
                select(func.count())
                .select_from(Conversation)
                .where(Conversation.owner_id == owner_id)
                .where(Conversation.ephemeral == False)  # noqa: E712 — SQL boolean compare
            ).one()

        return await in_session(self._engine, work)

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

    async def titles(self, conversation_ids: list[str], owner_id: str) -> dict[str, str]:
        """The titles of the owner's conversations among ``conversation_ids``, keyed by id.

        Untitled threads and ids the owner doesn't have are absent. This is deliberately
        narrower than :meth:`get_summary` — no message count, no last-message preview, and
        one query for the whole set. The runs listing wants a name per run and nothing
        else; asking for a full summary per run made it read every thread's rows.
        """
        wanted = list(dict.fromkeys(conversation_ids))
        if not wanted:
            return {}

        def work(session: Session) -> list[Conversation]:
            return list(
                session.exec(
                    select(Conversation).where(
                        Conversation.owner_id == owner_id,
                        Conversation.id.in_(wanted),  # type: ignore[attr-defined]
                    )
                ).all()
            )

        rows = await in_session(self._engine, work)
        opened = ((row.id, self._open_title(row)) for row in rows)
        return {cid: title for cid, title in opened if title is not None}

    async def messages_view(self, conversation_id: str) -> list[MessageView]:
        """The active path projected to render-ready user/assistant turns (reasoning
        split out, tool calls stitched to results), each carrying its branch node id
        and version index/count so the operator can regenerate, edit, or cycle it."""
        tree = await self._tree(conversation_id)
        nodes = _view_nodes(tree.active_path())
        compacted_ids = frozenset(n.id for n in nodes if n.compacted)
        views = project_tree([(n.id, n.message) for n in nodes], compacted_ids=compacted_ids)
        for view in views:
            node = tree.nodes.get(view.id)
            if node is not None:
                view.pinned = node.pinned
                view.attachment_ids = node.attachment_ids
                view.blocked_reason = node.blocked_reason
            siblings = tree.siblings(view.id)
            if siblings:
                view.version_count = len(siblings)
                view.version_index = siblings.index(view.id) if view.id in siblings else 0
        return views

    def _seal_title(self, title: str | None) -> str | None:
        """A title on its way to the DB. ``None`` stays ``None`` — an untitled thread has
        no ciphertext, which is not the same as one whose title is the empty string."""
        return None if title is None else self._vault.encrypt_str(title)

    def _open_title(self, conversation: Conversation) -> str | None:
        """A title on its way out — sealed, or the legacy cleartext of a row the startup
        backfill hasn't reached yet, so a half-migrated DB never renders a garbled or
        missing thread name."""
        return open_sealed(self._vault, conversation.title_enc, conversation.title)

    async def set_title(self, conversation_id: str, title: str | None) -> None:
        """Rename a conversation (and bump its updated_at)."""
        title_enc = self._seal_title(title)

        def work(session: Session) -> None:
            conversation = session.get(Conversation, conversation_id)
            if conversation is not None:
                conversation.title_enc = title_enc
                # A rename supersedes any legacy cleartext this row still carried, so drop
                # it here rather than leaving the old name readable until the backfill runs.
                conversation.title = None
                conversation.updated_at = datetime.now(UTC)

        await in_session(self._engine, work)

    async def set_title_if_absent(self, conversation_id: str, title: str) -> bool:
        """Set the title only when the conversation has none yet; return whether it
        was applied. This is the authoritative "fill, don't overwrite" guard for
        auto-titling — it can never clobber a name the operator chose, and a caller
        only announces the title when this returns True. Atomic within one session
        (check-and-set), so it is safe against a concurrent rename."""

        title_enc = self._vault.encrypt_str(title)

        def work(session: Session) -> bool:
            conversation = session.get(Conversation, conversation_id)
            # "Has a name already" is asked of the *effective* title, so a legacy
            # cleartext name still blocks an auto-title from clobbering it.
            if conversation is None or (self._open_title(conversation) or "").strip():
                return False
            conversation.title_enc = title_enc
            conversation.title = None
            conversation.updated_at = datetime.now(UTC)
            return True

        return await in_session(self._engine, work)

    async def binding(self, conversation_id: str) -> ConversationBinding:
        """This thread's binding — the facts a run needs to know where it works and how far
        it may go, read together so no path can pick up one and default the others.

        A missing conversation reads as an unfiled Normal thread at the default level,
        which is the same answer a stateless turn gets and the safe one: Normal never
        touches the host.
        """

        def work(session: Session) -> ConversationBinding:
            conversation = session.get(Conversation, conversation_id)
            if conversation is None:
                return ConversationBinding()
            # Both columns are plain strings, so an unrecognised value (a restored backup
            # from a future version, a hand-edited row) is normalised through its registry
            # rather than reaching the resolver as something it has no row for. They
            # degrade in opposite directions and each towards the answer that does least.
            return ConversationBinding(
                mode=mode_spec(conversation.mode).id,
                project_id=conversation.project_id,
                permission=permission_level(conversation.permission_level),
            )

        return await in_session(self._engine, work)

    async def set_permission_level(self, conversation_id: str, level: str) -> PermissionLevel:
        """Move this thread to ``level``, returning what it is now.

        The one binding fact that moves after creation, and the reason it is a plain write
        rather than a new row: the level is the operator's live control, changed by sending
        at a different level or by accepting a plan, and a thread mid-flight keeps every
        other thing about itself. A run already in progress is unaffected — it carries the
        level it started with on its own binding, so a switch lands on the next turn rather
        than halfway through this one.

        Deliberately does not bump ``updated_at``: choosing what the model may do next is
        not activity in the thread, the same reasoning the compaction override follows.
        """
        resolved = permission_level(level)

        def work(session: Session) -> None:
            conversation = session.get(Conversation, conversation_id)
            if conversation is not None:
                conversation.permission_level = resolved

        await in_session(self._engine, work)
        return resolved

    async def get_compaction_override(self, conversation_id: str) -> bool | None:
        """This conversation's auto-compaction override — ``None`` inherits the operator
        default, ``True``/``False`` force it on/off for this thread."""

        def work(session: Session) -> bool | None:
            conversation = session.get(Conversation, conversation_id)
            return conversation.auto_compact_override if conversation is not None else None

        return await in_session(self._engine, work)

    async def set_compaction_override(self, conversation_id: str, override: bool | None) -> None:
        """Set (or clear, with ``None``) this conversation's auto-compaction override.
        A quiet preference, so it deliberately does not bump ``updated_at`` (it isn't
        activity)."""

        def work(session: Session) -> None:
            conversation = session.get(Conversation, conversation_id)
            if conversation is not None:
                conversation.auto_compact_override = override

        await in_session(self._engine, work)

    async def get_overhead(self, conversation_id: str) -> TurnOverhead | None:
        """What this thread's last turn carried besides the conversation — the standing
        brief and the tool schemas, itemised.

        The half of the context readout that a cold load cannot measure: neither reaches
        the message history, so a reopened thread has only the footprint total without
        this. ``None`` for a thread that has not run a turn since this was recorded, and
        the breakdown is then absent rather than guessed."""

        def work(session: Session) -> Any:
            conversation = session.get(Conversation, conversation_id)
            return conversation.context_overhead if conversation is not None else None

        return TurnOverhead.from_dict(await in_session(self._engine, work))

    async def set_overhead(self, conversation_id: str, overhead: TurnOverhead | None) -> None:
        """Record what the turn that just ran weighed, for the next cold load of *this*
        thread.

        A failed measurement is ignored rather than stored as absence: the previous good
        figure still describes this thread's configuration better than nothing does. Like
        the compaction override, this deliberately does not bump ``updated_at`` — it is
        bookkeeping about a turn, not activity of its own."""
        if overhead is None:
            return

        def work(session: Session) -> None:
            conversation = session.get(Conversation, conversation_id)
            if conversation is not None:
                conversation.context_overhead = overhead.as_dict()

        await in_session(self._engine, work)

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
        self._owners.pop(conversation_id, None)

    def record(
        self,
        conversation_id: str,
        new_messages: list[ModelMessage],
        attachment_ids: list[str] | None = None,
        persisted: list | None = None,
        blocked_reason: str | None = None,
        timings: list[ResponseTiming] | None = None,
    ) -> None:
        """Hot path: extend the tree off the active leaf and queue the durable write.

        Only projects and serializes here (no vault) — the drainer encrypts just
        before the write, on the lock-aware side of the queue. New messages branch
        automatically when a prior regenerate/edit moved the active leaf back.
        ``attachment_ids``/``persisted`` belong to the turn's user request (the first one):
        the ids are stamped on its node + row (chip rendering), and when ``persisted`` is
        given the request's *live* attachment content is replaced by that capped set before
        serialize — so replayed history carries only the retained-up-to-cap content, never
        the uncapped live payload. Installing it lives here (not in the engine) because
        *what the durable blob contains* is the store's job. ``blocked_reason``, when the
        turn ended blocked (a usage/loop/context/time bound), stamps the turn's branch
        node — the first response, matching how ``project_tree`` keys an assistant view —
        so a reload carries the same persistent stop marker the live stream showed.
        ``timings``, when the caller measured them, are the run's per-response wall-clock
        in the order the responses were produced — zipped onto the response nodes below,
        so the readout can total a cold thread's time the way it totals its tokens."""
        if not new_messages:
            return
        tree = self._cache_get(conversation_id)
        if tree is None:
            # Nothing cached: either a brand-new conversation (`create_conversation`
            # seeds an empty tree, so normally this doesn't fire) or one whose id no
            # longer exists — a delete that landed while this turn was still running.
            # An empty tree is right for the first case and a resurrected ghost in the
            # second, so `_persist_messages` re-checks the row before writing.
            tree = self._cache_put(conversation_id, _Tree())
        added = tree.append_chain(new_messages)
        # A turn blocked before it produced a response (a time/cancel bound tripping in
        # the pre-model setup window) has no response node to carry the marker — so the
        # turn's user request carries it instead, and a reload still shows the persistent
        # stop marker (under the operator's own message) rather than dropping it.
        blocked_on_request = bool(blocked_reason) and not any(
            isinstance(n.message, ModelResponse) for n in added
        )
        rows: list[_Row] = []
        stamped = False
        blocked_stamped = False
        # One timing per response, consumed in the order the responses appear — the
        # order the translator produced them in. A short (or absent) list simply leaves
        # the remaining responses unmeasured: a mismatch means the run stopped somewhere
        # the stopwatch didn't reach, and a null there is the honest answer, where
        # misaligning the rest would attribute one response's time to another.
        pending_timings = iter(timings or ())
        for node in added:
            # The attached files belong to this turn's user request (the first one);
            # install the capped content and stamp the ids before we project/serialize.
            if not stamped and getattr(node.message, "kind", "") == "request":
                if attachment_ids:
                    node.attachment_ids = list(attachment_ids)
                install_persisted_attachments(node.message, persisted)
                if blocked_on_request:
                    node.blocked_reason = blocked_reason
                stamped = True
            if (
                not blocked_stamped
                and blocked_reason
                and not blocked_on_request
                and isinstance(node.message, ModelResponse)
            ):
                node.blocked_reason = blocked_reason
                blocked_stamped = True
            if isinstance(node.message, ModelResponse):
                timing = next(pending_timings, None)
                if timing is not None:
                    node.llm_ms = timing.llm_ms
                    node.ttft_ms = timing.ttft_ms
                    node.tool_ms = timing.tool_ms
            kind, text = _project(node.message)
            blob = _MESSAGE.dump_json(node.message).decode()
            rows.append(
                _Row(
                    id=node.id,
                    parent_id=node.parent_id,
                    seq=node.seq,
                    kind=kind,
                    text=text,
                    blob=blob,
                    attachment_ids=node.attachment_ids,
                    blocked_reason=node.blocked_reason,
                    llm_ms=node.llm_ms,
                    ttft_ms=node.ttft_ms,
                    tool_ms=node.tool_ms,
                )
            )
        self._submit(
            _PersistJob(
                kind="messages",
                conversation_id=conversation_id,
                active_leaf_id=tree.active_leaf_id,
                rows=rows,
                model=_active_path_model(tree.active_path()),
            )
        )

    # ── Tree navigation (regenerate / edit / rewind / version switch / delete) ──
    #
    # Each moves the active leaf in memory (immediately authoritative) and queues
    # the matching durable update. Regenerate/edit only reposition the leaf — the
    # caller then launches a normal turn whose record() writes the new branch.

    def _move_leaf(self, conversation_id: str, leaf_id: str | None) -> None:
        """Queue an active-leaf move (the in-memory tree is already updated). The
        new active path can run on a different model than before (switching to an
        older version), so the denormalized model rides along with the pointer."""
        tree = self._cache.get(conversation_id)
        model = _active_path_model(tree.active_path()) if tree is not None else None
        self._submit(
            _PersistJob(
                kind="active_leaf",
                conversation_id=conversation_id,
                active_leaf_id=leaf_id,
                model=model,
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

    async def fork(self, conversation_id: str, message_id: str, owner_id: str) -> str | None:
        """Copy this thread's history up to ``message_id`` into a **new** conversation.

        Distinct from regenerate/edit/rewind, which all move the active leaf *within* one
        thread's tree: a fork produces an independent conversation the operator can take
        in a different direction while the original stays exactly as it was. Returns the
        new conversation's id, or None when ``message_id`` isn't on the active path.

        What it deliberately does **not** copy is the interesting part:

        - **runs and pins.** A run belongs to the turn that produced it; a pin is a
          bookmark on the original.
        - **the workspace's contents.** The copied transcript may name paths in a sandbox
          the fork does not have — already true of any replayed thread, and
          ``attachments_provision`` is the way back. A **coding** fork is different and is
          handled by the caller: it branches from the source conversation's branch rather
          than the project's base ref, so the transcript and the tree agree.

        The copy is built in memory and drains through the normal write-behind path, so
        it is sealed on write like everything else.
        """
        tree = await self._tree(conversation_id)
        path = tree.active_path()
        ids = [n.id for n in path]
        if message_id not in ids:
            return None
        idx = ids.index(message_id)
        # The same "tail of this turn" rule `rewind` uses, so forking from an assistant
        # turn carries its tool exchanges rather than cutting the turn in half.
        if not _is_user_prompt(path[idx].message):
            while idx + 1 < len(path) and not _is_user_prompt(path[idx + 1].message):
                idx += 1
        copied = path[: idx + 1]

        source = await self.get_summary(conversation_id, owner_id)
        binding = await self.binding(conversation_id)
        new_id_ = await self.create_conversation(
            owner_id,
            title=_forked_title(source.title if source is not None else None),
            project_id=binding.project_id,
            mode=binding.mode,
            # The level rides along with the rest of the binding: a fork of a thread the
            # operator had dropped to Manual must not come back at the mode's default.
            permission=binding.permission,
        )

        forked = self._cache_get(new_id_) or self._cache_put(new_id_, _Tree())
        rows: list[_Row] = []
        parent: str | None = None
        for seq, node in enumerate(copied):
            # `compacted` rides along but `compacted_through` deliberately does not: it
            # names a node id in the *source* tree, so carrying it would leave a dangling
            # reference for `model_history` to walk into. The checkpoint keeps its summary
            # (real history) and reads as covering everything before it, which is true.
            fresh = _Node(
                id=new_id(),
                parent_id=parent,
                seq=seq,
                message=node.message,
                # Not `pinned`: a bookmark belongs to the thread it was placed in.
                attachment_ids=list(node.attachment_ids),
                blocked_reason=node.blocked_reason,
                compacted=node.compacted,
            )
            forked.add(fresh)
            kind, text = _project(fresh.message)
            rows.append(
                _Row(
                    id=fresh.id,
                    parent_id=fresh.parent_id,
                    seq=fresh.seq,
                    kind=kind,
                    text=text,
                    blob=_MESSAGE.dump_json(fresh.message).decode(),
                    attachment_ids=fresh.attachment_ids,
                    blocked_reason=fresh.blocked_reason,
                    compacted=fresh.compacted,
                )
            )
            parent = fresh.id
        forked.active_leaf_id = parent
        self._submit(
            _PersistJob(
                kind="messages",
                conversation_id=new_id_,
                active_leaf_id=parent,
                rows=rows,
                model=_active_path_model(forked.active_path()),
            )
        )
        return new_id_

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
        self._submit(
            _PersistJob(
                kind="pin",
                conversation_id=conversation_id,
                message_id=message_id,
                pinned=pinned,
            )
        )
        return True

    async def clear_blocked_reason(self, conversation_id: str, message_id: str) -> bool:
        """Retire the persistent stop marker on the turn whose branch node is
        ``message_id``. Returns False if the node is unknown or was never blocked.

        A stop marker says "this turn was cut short and nothing has been done about
        it" — a standing prompt to resume. Once the operator *has* resumed it, the
        marker is answering a question nobody is asking any more, so it is cleared
        rather than left to accumulate down the transcript. Clearing is durable (it
        rewrites the node and its row) because the marker itself is durable: a
        reload must not resurrect a stop the operator already handled. Queued behind
        any in-flight message writes so it lands on a persisted row.

        An unrecognized ``message_id`` falls back to the *newest* blocked turn on the
        active path. A live client names the turn by the id it is showing, and for a
        turn that stopped before anything was persisted that id is the client's own
        optimistic one — never a node id here. Such an id can only ever name the turn
        being streamed, i.e. the newest, so the fallback is unambiguous even with
        older markers still standing further up the thread — honour the intent rather
        than leaving a stop the operator has visibly resolved."""
        tree = await self._tree(conversation_id)
        node = tree.nodes.get(message_id)
        if node is None:
            node = next(
                (n for n in reversed(tree.active_path()) if n.blocked_reason is not None),
                None,
            )
        if node is None or node.blocked_reason is None:
            return False
        node.blocked_reason = None
        self._submit(
            _PersistJob(
                kind="unblock",
                conversation_id=conversation_id,
                message_id=node.id,
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
        self._submit(
            _PersistJob(
                kind="delete",
                conversation_id=conversation_id,
                active_leaf_id=tree.active_leaf_id,
                deleted_ids=doomed,
                model=_active_path_model(tree.active_path()),
            )
        )
        return True

    # ── Attachment provenance & the delete-choice safety check ──────────────────
    #
    # ``attachment_ids`` is a clear JSON column, so both read it directly — no decrypt.
    # The first answers "which images are still referenced from chats"; the delete flow uses
    # the second to purge an attached image only when nothing surviving still references it.

    async def referenced_upload_ids(
        self, owner_id: str, *, exclude_conversation_id: str | None = None
    ) -> set[str]:
        """Every upload id still referenced by one of the owner's messages — the union of
        ``attachment_ids`` across the durable record (a DB scan) overlaid with the warm
        in-memory trees (which can run ahead of the write-behind drainer). Pass
        ``exclude_conversation_id`` to ignore one conversation — how the delete flow asks
        "does anything *else* still reference this image?"."""

        def work(session: Session) -> set[str]:
            stmt = (
                select(Message.attachment_ids)
                .join(Conversation, Message.conversation_id == Conversation.id)
                .where(Conversation.owner_id == owner_id)
            )
            if exclude_conversation_id is not None:
                stmt = stmt.where(Message.conversation_id != exclude_conversation_id)
            refs: set[str] = set()
            for ids in session.exec(stmt):
                if ids:
                    refs.update(ids)
            return refs

        refs = await in_session(self._engine, work)
        for cid, tree in self._cache.items():
            if cid == exclude_conversation_id:
                continue
            for node in tree.nodes.values():
                if node.attachment_ids:
                    refs.update(node.attachment_ids)
        return refs

    async def orphaned_attachments_for_delete(
        self, owner_id: str, conversation_id: str, *, message_id: str | None = None
    ) -> list[str]:
        """The upload ids that would lose their last reference if this delete proceeds —
        attached only inside the doomed scope and nowhere surviving. ``message_id`` scopes
        the delete to that turn's subtree; ``None`` means the whole conversation.

        Computed from the authoritative in-memory tree (ahead of the drainer, so write-
        behind lag can't trigger a false purge), minus every surviving reference: this
        conversation's nodes *outside* the doomed set, plus every *other* conversation. The
        surviving set is a deliberate superset (DB ∪ warm caches), which can only ever
        spare an image, never purge one still in use. Returns ids regardless of mime — the
        caller filters to images."""
        tree = await self._tree(conversation_id)
        if message_id is not None:
            if message_id not in tree.nodes:
                return []
            doomed = set(tree.subtree_ids(message_id))
        else:
            doomed = set(tree.nodes)

        doomed_refs: set[str] = set()
        surviving_refs: set[str] = set()
        for node_id, node in tree.nodes.items():
            if not node.attachment_ids:
                continue
            bucket = doomed_refs if node_id in doomed else surviving_refs
            bucket.update(node.attachment_ids)
        surviving_refs |= await self.referenced_upload_ids(
            owner_id, exclude_conversation_id=conversation_id
        )
        return sorted(doomed_refs - surviving_refs)

    async def detach_upload(self, owner_id: str, upload_id: str) -> None:
        """Drop ``upload_id`` from every message that lists it as an attachment — both the
        warm in-memory trees (authoritative, possibly ahead of the drainer) and the durable
        rows. Called when an upload is hard-deleted, so no conversation strands a dangling
        attachment reference to bytes that no longer exist. ``attachment_ids`` is a clear
        JSON column, so this neither decrypts nor reseats the tree's structure."""
        for tree in self._cache.values():
            for node in tree.nodes.values():
                if node.attachment_ids and upload_id in node.attachment_ids:
                    node.attachment_ids = [a for a in node.attachment_ids if a != upload_id]

        def work(session: Session) -> None:
            rows = session.exec(
                select(Message)
                .join(Conversation, Message.conversation_id == Conversation.id)
                .where(Conversation.owner_id == owner_id)
            ).all()
            for row in rows:
                if row.attachment_ids and upload_id in row.attachment_ids:
                    row.attachment_ids = [a for a in row.attachment_ids if a != upload_id]
                    session.add(row)

        await in_session(self._engine, work)

    # ── Write-behind drainer ───────────────────────────────────────────────────

    async def _owner_of(self, conversation_id: str) -> str | None:
        """The conversation's owner, memoized. A conversation never changes hands, and
        this sits on the write-behind path — one extra round trip per persisted turn,
        purely to re-read an immutable column."""
        cached = self._owners.get(conversation_id)
        if cached is not None:
            return cached

        def work(session: Session) -> str | None:
            conversation = session.get(Conversation, conversation_id)
            return conversation.owner_id if conversation is not None else None

        owner_id = await in_session(self._engine, work)
        if owner_id is not None:
            self._owners[conversation_id] = owner_id
        return owner_id

    def _submit(self, job: _PersistJob) -> None:
        """Queue durable work and pin its conversation in the cache until it lands.

        The pin is what makes eviction safe: between this call and the write, the
        cached tree is the only place the turn's structure exists.
        """
        self._pending[job.conversation_id] += 1
        self._worker.submit(job)

    def _release(self, job: _PersistJob) -> None:
        """Drop this job's pin once it has reached a terminal disposition."""
        conversation_id = job.conversation_id
        if self._pending[conversation_id] <= 1:
            del self._pending[conversation_id]  # keep the Counter from growing forever
        else:
            self._pending[conversation_id] -= 1

    async def _persist(self, job: _PersistJob) -> None:
        if job.kind == "messages":
            await self._persist_messages(job)
        elif job.kind == "active_leaf":
            await self._persist_active_leaf(job)
        elif job.kind == "delete":
            await self._persist_delete(job)
        elif job.kind == "pin":
            await self._persist_pin(job)
        elif job.kind == "unblock":
            await self._persist_unblock(job)
        # Deliberately not in a `finally`: a raise here is retried by the worker, and
        # the conversation must stay pinned across those attempts. A job that exhausts
        # its retries releases through `_on_drop` instead.
        self._release(job)

    async def _persist_messages(self, job: _PersistJob) -> None:
        # Embed off the DB thread, before the write — vectors travel into work() as
        # encrypted blobs keyed by row id. Best-effort: a missing/degraded embedder
        # yields no vectors, and those messages persist for keyword-only recall.
        vectors = await self._embed_rows(job)

        def work(session: Session) -> None:
            # The conversation may have been deleted while this write sat in the
            # queue — don't resurrect it as orphaned message rows.
            conversation = session.get(Conversation, job.conversation_id)
            if conversation is None:
                return
            for row in job.rows:
                model, dim, vector_enc = vectors.get(row.id, (None, None, None))
                session.add(
                    Message(
                        id=row.id,
                        conversation_id=job.conversation_id,
                        parent_id=row.parent_id,
                        seq=row.seq,
                        kind=row.kind,
                        text=self._vault.encrypt_str(row.text),
                        blob=self._vault.encrypt_str(row.blob),
                        attachment_ids=row.attachment_ids,
                        blocked_reason=row.blocked_reason,
                        compacted=row.compacted,
                        compacted_through=row.compacted_through,
                        llm_ms=row.llm_ms,
                        ttft_ms=row.ttft_ms,
                        tool_ms=row.tool_ms,
                        embedding_enc=vector_enc,
                        embedding_model=model,
                        embedding_dim=dim,
                    )
                )
            conversation.active_leaf_id = job.active_leaf_id
            conversation.model = job.model
            conversation.updated_at = datetime.now(UTC)

        await in_session(self._engine, work)

    async def _embed_rows(
        self, job: _PersistJob
    ) -> dict[str, tuple[str | None, int | None, str | None]]:
        """Embed each row's searchable text for cross-chat recall, returning
        ``row_id -> (model, dim, encrypted_vector)``. Empty when there's nothing to
        embed or the embedder is unavailable — the write then stores no vectors."""
        if self._embedder is None:
            return {}
        texts = [(row.id, row.text) for row in job.rows if row.text.strip()]
        if not texts:
            return {}

        owner_id = await self._owner_of(job.conversation_id)
        if owner_id is None:
            return {}
        # Embedding is strictly best-effort: it must never fail or stall a durable
        # write. A degraded embedder is the silent, expected case; any other error
        # (timeout, 5xx, connection reset) is logged and the turn persists without a
        # vector — keyword recall still covers it. Letting the embed raise here would
        # consume the drainer's retry budget and could ultimately drop the turn.
        try:
            batch = await self._embedder.embed(owner_id, [text for _id, text in texts])
        except DegradedCapabilityError:
            return {}
        except Exception:
            logger.exception(
                "embedding messages for conversation %s failed; persisting without vectors",
                job.conversation_id,
            )
            return {}
        return {
            row_id: (batch.model, batch.dim, encode_vector(self._vault, vector))
            for (row_id, _text), vector in zip(texts, batch.vectors, strict=False)
        }

    async def backfill_embeddings(self, owner_id: str, *, batch_size: int = 64) -> int:
        """Lift messages with *no* vector into the index — the startup backlog case
        (persisted before an embedding endpoint existed). The NULL-only slice of
        :meth:`reindex_embeddings`."""
        return await self.reindex_embeddings(owner_id, current_model=None, batch_size=batch_size)

    async def reindex_embeddings(
        self, owner_id: str, *, current_model: str | None = None, batch_size: int = 64
    ) -> int:
        """Best-effort: (re-)embed content-bearing messages whose vector is missing,
        or — when ``current_model`` is given — was produced by a different model than
        the one now configured. The latter is the heal path after the operator changes
        the embedding model: EMB-2 segregates vectors by model, so stale vectors fall
        back to keyword search until re-embedded into the current space. Returns how
        many were embedded. A no-op when the embedder is unavailable, so a backlog
        stays keyword-searchable until an embedder exists, then this lifts it."""
        if self._embedder is None:
            return 0

        def pending(session: Session) -> list[tuple[str, str]]:
            query = (
                select(Message.id, Message.text)
                .join(Conversation, Message.conversation_id == Conversation.id)
                .where(Conversation.owner_id == owner_id)
            )
            if current_model is None:
                query = query.where(Message.embedding_enc.is_(None))  # type: ignore[union-attr]
            else:
                query = query.where(
                    or_(
                        Message.embedding_enc.is_(None),  # type: ignore[union-attr]
                        Message.embedding_model != current_model,
                    )
                )
            rows = session.exec(query).all()
            return [(rid, self._vault.decrypt_str(text)) for rid, text in rows]

        rows = await in_session(self._engine, pending)
        items = [(rid, text) for rid, text in rows if text.strip()]
        assert self._embedder is not None  # guarded at the top of this method
        return await embed_and_seal_rows(
            engine=self._engine,
            vault=self._vault,
            embedder=self._embedder,
            owner_id=owner_id,
            model_cls=Message,
            pending=items,
            batch_size=batch_size,
        )

    async def _persist_active_leaf(self, job: _PersistJob) -> None:
        def work(session: Session) -> None:
            conversation = session.get(Conversation, job.conversation_id)
            if conversation is not None:
                conversation.active_leaf_id = job.active_leaf_id
                conversation.model = job.model
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
            conversation.model = job.model
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

    async def _persist_unblock(self, job: _PersistJob) -> None:
        def work(session: Session) -> None:
            # Like the pin write, deliberately does not bump updated_at: retiring a
            # stop marker is bookkeeping on an old turn, and the turn that actually
            # resumes it floats the conversation on its own.
            row = session.get(Message, job.message_id) if job.message_id else None
            if row is not None:
                row.blocked_reason = None

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
        # Terminal, so the pin goes even though the write never landed — holding it
        # would keep this conversation resident for the life of the process.
        self._release(job)
