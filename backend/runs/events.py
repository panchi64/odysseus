"""Pillar II — the event protocol (the backend↔frontend contract).

The frozen v1 typed event union. Framing: SSE, each frame's ``id:`` is the
per-run monotonic ``seq`` and ``data:`` is the flat JSON envelope
``{type, seq, ts, ...payload}``. Naming is ``entity.event``, dot.lowercase —
past-tense verbs for things that happened, ``delta``/``progress`` for streams.

Producers build a typed body (e.g. ``AnswerDelta(text=...)``); the Run stamps
``seq``/``ts`` at emit time and wraps it in an :class:`Event`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

PROTOCOL_VERSION = 1


def now_utc() -> datetime:
    return datetime.now(UTC)


class _Body(BaseModel):
    model_config = ConfigDict(frozen=True)


# --- Run ---------------------------------------------------------------------
class RunStarted(_Body):
    type: Literal["run.started"] = "run.started"
    run_id: str
    kind: str
    protocol_version: int = PROTOCOL_VERSION


class ContextThresholds(_Body):
    """Where a filling context window stops being unremarkable and starts being a
    problem — the two boundaries the gauge changes colour on.

    **Operator-tunable**, because the point at which the remaining room stops being
    enough is a property of how someone works rather than of the model: a thread of
    long tool results can spend the last quarter of a window in a single turn, while a
    short back-and-forth has a dozen turns left at the same fullness. A fixed boundary
    is therefore either early enough to be noise for one operator or late enough to be
    useless for the other.

    Fractions, not percentages — the same 0-1 quantity :attr:`ContextWindow.fraction`
    and auto-compaction's own threshold already carry, so nothing here has to agree on
    a second convention.

    ``warn`` strictly below ``alert`` is an invariant, not a preference: equal
    boundaries make the amber band unreachable, and inverted ones walk the gauge
    backwards through severity as it fills. Enforced here so that the one construction
    path is also the one check."""

    warn: float = Field(gt=0, lt=1)
    alert: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def _ordered(self) -> ContextThresholds:
        if self.warn >= self.alert:
            raise ValueError("the warn threshold must be below the alert threshold")
        return self


#: The boundaries in force when the operator hasn't moved them. 75/90 leaves roughly a
#: turn or two of warning at typical turn sizes before the window is genuinely tight,
#: and both sit below auto-compaction's own 0.95 default - so on a thread with
#: compaction on, the gauge reddens while there is still something the fold can do.
DEFAULT_CONTEXT_THRESHOLDS = ContextThresholds(warn=0.75, alert=0.9)


class ContextSegment(_Body):
    """One line item inside a group — a tool category, a contributor to the standing
    brief, a class of message content.

    **Present only when it weighs something.** The segment list is not a fixed roster
    with zeros in it: a thread that has called no tools carries no `tool_results` row, a
    catalog with no MCP servers connected carries no `external` row, and both appear the
    moment they start costing the window. That is the difference between a readout the
    operator scans and a form they have to read — the rows that are there are the rows
    that matter.

    ``id`` is a slug, not a label: the tool category as the operator's own settings page
    names it, the instruction provider's slug, or the message class. The wording is the
    client's — a readout row is presentation, and the backend has no business choosing
    sentence case. ``count`` is the population behind the figure where one exists (tools
    in a category, `null` elsewhere), because "22k of schemas" and "22k of schemas across
    68 tools" lead to different decisions."""

    id: str
    group: Literal["brief", "tools", "messages"]
    tokens: int
    count: int | None = None


class ContextComposition(_Body):
    """What the occupied part of the window is actually holding.

    Two resolutions of one measurement. The three totals are exhaustive by construction —
    they are scaled to sum to :attr:`ContextWindow.used` (see ``services.context_budget``)
    — so the operator can read them as a whole rather than wondering what the remainder
    is. ``segments`` itemises those same tokens without adding any: each segment belongs
    to exactly one group, and a group's segments sum to its total.

    The itemisation is what makes the readout answer the *next* question. "Tools are 40%
    of your window" is where the three-way split stops and where the operator's actual
    decision starts — which tools, and can they be switched off. Empty when a
    measurement could reach the totals but not the detail, so the coarse reading never
    depends on the fine one.

    Every figure is an **estimate anchored to the provider's total**: the split is ours,
    measured from what we assembled, because no provider reports one. Surfaces render
    these with a `~`."""

    system: int  # the standing brief: instructions + system prompt
    tools: int  # every tool name, description and JSON schema handed to the model
    messages: int  # the conversation itself
    segments: tuple[ContextSegment, ...] = ()


class ContextWindow(_Body):
    """How full a model's context window is after a turn — the single owner of
    the fullness derivation and its severity thresholds. Built by
    :meth:`from_usage` and emitted both live (run metrics) and on load
    (conversation detail), so clients render one shape from either source."""

    used: int  # tokens occupying the window: last response's prompt + generation
    window: int  # the model's context window
    fraction: float  # used / window, clamped to 0–1
    level: Literal["nominal", "warn", "alert"]
    # What `used` is made of, when it could be measured. Null on a thread whose turns all
    # predate the measurement, and on a cold load of one — the split is captured while a
    # request is being assembled, and a reload has no request to look at.
    parts: ContextComposition | None = None

    @classmethod
    def from_used(
        cls,
        used: int | None,
        window: int | None,
        thresholds: ContextThresholds = DEFAULT_CONTEXT_THRESHOLDS,
        parts: ContextComposition | None = None,
    ) -> ContextWindow | None:
        """Derive the window state from the context footprint (``used``), or None
        when there's no ceiling to measure against or no footprint was reported.

        ``thresholds`` are the operator's severity boundaries; the default is what a
        caller with no settings store to consult gets. The *level* is resolved here and
        travels on the wire, so that the gauge, the overflow warning, and anything else
        keying off severity read one boundary rather than each re-deriving it — the
        client renders a level, it never decides one."""
        if not window or used is None:
            return None
        fraction = min(1.0, used / window)
        level = (
            "alert"
            if fraction >= thresholds.alert
            else "warn"
            if fraction >= thresholds.warn
            else "nominal"
        )
        return cls(used=used, window=window, fraction=fraction, level=level, parts=parts)


class RunMetrics(_Body):
    """What the thread has cost so far — the readout under the composer.

    **Conversation-cumulative, not per-run.** Every count here spans the whole active
    path: the run seeds them from the conversation's persisted totals and accumulates
    its own on top. A per-run frame was what this used to be, and it made the line
    unreadable — the numbers reset to zero at the start of every turn, so the one
    moment the operator most wants to know what a long thread has spent is the moment
    the readout says nothing.

    Absent, never zero. A null field means *not measured* — a provider that reports no
    cache tokens, a turn that streamed no content to time. Zero means measured as zero.
    The distinction is the whole reason these are nullable, and it is what lets the UI
    omit a segment rather than assert a flattering 0%.
    """

    type: Literal["run.metrics"] = "run.metrics"
    steps: int = 0
    tool_calls: int = 0
    # Completed exchanges on the active path — what a reader calls a "turn", where
    # `steps` counts the model round-trips a turn took internally.
    turns: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    # Prompt tokens the provider served from its own cache. **Provider-reported, so
    # null on every endpoint that doesn't report it** — most OpenAI-compatible and
    # local servers. This is the one number here we can't measure ourselves, and a 0
    # would read as "your caching is broken" rather than "nobody said".
    cache_read_tokens: int | None = None
    # Wall-clock, measured by us around our own node iteration so it means the same
    # thing on every endpoint (see `agent/timings.py`). `llm_ms` is the full model
    # round-trip including connect and queue — the wait the operator actually sat
    # through — not a claim about the provider's inference time.
    llm_ms: int | None = None
    tool_ms: int | None = None
    # Summed time-to-first-content and the number of responses that produced any, kept
    # apart so the average survives being added to another run's totals. A single
    # pre-averaged field could not be accumulated without drifting.
    ttft_ms_total: int | None = None
    ttft_samples: int = 0
    # The model's context window, when known — the ceiling the derived `context`
    # measures against. Null when the endpoint declares none.
    context_window: int | None = None
    # The context footprint after this turn: the *last* model response's prompt +
    # generation (what the next turn carries forward). Deliberately NOT the run's
    # cumulative input/output above — those sum every internal model request and
    # would overstate fullness several-fold on tool-calling or multi-turn runs.
    context_used: int | None = None

    # The operator's severity boundaries, seeded onto the Run at turn start and read
    # by `context` below. Deliberately **not serialized**: it is an input to the
    # derivation, not part of the readout, and putting it on the wire would invite a
    # client to re-derive the level it is already being handed.
    context_thresholds: ContextThresholds = Field(
        default=DEFAULT_CONTEXT_THRESHOLDS, exclude=True
    )

    # How that footprint splits across the standing brief, the tool schemas and the
    # conversation. Measured during the turn (the tool definitions are only knowable while
    # a request is being assembled), so it rides on the frame rather than being derived
    # from it.
    context_parts: ContextComposition | None = None

    @computed_field
    @property
    def context(self) -> ContextWindow | None:
        """The context-window fullness after this turn — null when unmeasurable
        (no window, or no footprint). Clients render it; they never derive it."""
        return ContextWindow.from_used(
            self.context_used, self.context_window, self.context_thresholds, self.context_parts
        )

    @computed_field
    @property
    def cache_hit_ratio(self) -> float | None:
        """Share of prompt tokens the provider served from cache, 0–1. Null when the
        provider reports no cache figure, or before any prompt tokens are counted."""
        if self.cache_read_tokens is None or not self.input_tokens:
            return None
        return min(1.0, self.cache_read_tokens / self.input_tokens)

    @computed_field
    @property
    def ttft_avg_ms(self) -> int | None:
        """Mean time to first content across the responses that produced any."""
        if not self.ttft_samples or self.ttft_ms_total is None:
            return None
        return round(self.ttft_ms_total / self.ttft_samples)

    @computed_field
    @property
    def output_tokens_per_second(self) -> float | None:
        """Generation throughput — output tokens over the time actually spent *generating*.

        That is ``llm_ms`` minus the time to first token, and the subtraction is the
        whole correctness of this figure rather than a refinement of it. ``llm_ms`` is
        the full round-trip: connect, queue, process the prompt, then generate. Only the
        last of those produces tokens. On a local model with a long thread the prefill
        can be most of the wall-clock — a 20s TTFT in front of 5s of generation is
        ordinary — so dividing by the total reported something like a fifth of the real
        rate, and got slower the longer the conversation grew even though the model was
        decoding at exactly the same speed.

        TTFT is precisely the non-generating head of the request, which is why it is the
        right thing to subtract. Both are summed over the same responses, so this is the
        thread's mean decode rate, not the last turn's.

        Still measured against model time and not elapsed time: the operator's wait also
        includes tool execution and their own thinking between turns, and dividing by
        that would report a rate that falls the longer they leave the tab open."""
        if not self.output_tokens or self.llm_ms is None:
            return None
        generating_ms = self.llm_ms - (self.ttft_ms_total or 0)
        # Non-positive means the arithmetic has nothing to say: a thread whose responses
        # were all TTFT and no generation, or timings recorded before this was measured.
        # Absent beats a number derived from a division we don't trust.
        if generating_ms <= 0:
            return None
        return self.output_tokens / (generating_ms / 1000)


class RunEnded(_Body):
    """The closing frame for a run that reached an *expected* end.

    A run closes with exactly one of `run.ended` or `run.error`, never both — the
    terminal frame has two shapes because the two carry different payloads, and a
    failure has a message and an exception kind where an expected end has an outcome
    and a detail. Readers treat either as end-of-stream (`isTerminal` on the client).
    `error` is deliberately absent from ``outcome`` for that reason: it is not an
    outcome this frame ever carries. Both are preceded by `run.metrics`.
    """

    type: Literal["run.ended"] = "run.ended"
    outcome: Literal["done", "blocked", "cancelled"]
    detail: str | None = None


class RunError(_Body):
    """The closing frame for a run that failed. See :class:`RunEnded` — these two are
    the same terminal position in the protocol, not a frame plus an extra."""

    type: Literal["run.error"] = "run.error"
    message: str
    kind: str | None = None


# --- Step --------------------------------------------------------------------
class StepStarted(_Body):
    type: Literal["step.started"] = "step.started"
    index: int
    title: str | None = None


class StepCompleted(_Body):
    type: Literal["step.completed"] = "step.completed"
    index: int


# --- Content (the reasoning/answer split) ------------------------------------
class ThinkingDelta(_Body):
    type: Literal["thinking.delta"] = "thinking.delta"
    text: str


class AnswerDelta(_Body):
    type: Literal["answer.delta"] = "answer.delta"
    text: str


# --- Tools (full args + results inline, not summaries) -----------------------
class ToolStarted(_Body):
    type: Literal["tool.started"] = "tool.started"
    tool_call_id: str
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class ToolProgress(_Body):
    type: Literal["tool.progress"] = "tool.progress"
    tool_call_id: str
    elapsed_s: float | None = None
    partial: str | None = None


class ToolCompleted(_Body):
    type: Literal["tool.completed"] = "tool.completed"
    tool_call_id: str
    name: str
    result: Any = None


class ToolFailed(_Body):
    type: Literal["tool.failed"] = "tool.failed"
    tool_call_id: str
    name: str
    error: str


# --- View (the conversation's one versioned output surface) ------------------
# The View is one canvas with a history of **versions** to compare plus an optional
# live **head**. A version is one ``view.snapshot`` (the captured workspace tree +
# how it previews); ``view.live`` / ``view.live.stopped`` are the interactive head
# overlaid on the latest version.
class ViewLive(_Body):
    """The agent started (or replaced) the View's live head — a running server.
    ``url`` is a token-gated proxy path on this same API origin
    (``/previews/{token}/…``) that streams the server's HTTP and WebSocket traffic
    out of the sandbox.

    Frontend contract: mount it as ``<iframe src={url}>`` with
    ``sandbox="allow-scripts allow-forms allow-popups"`` — deliberately **without**
    ``allow-same-origin``, so the framed (model-generated) app runs in an opaque
    origin and cannot act as the operator against the API. The token in the path is
    the credential, so no auth header is needed and relative subresources/WebSockets
    resolve automatically. ``url`` already carries the entry path when one was given,
    so it renders the page rather than a directory listing. Additive to v1; no bump."""

    type: Literal["view.live"] = "view.live"
    conversation_id: str
    url: str  # "/previews/{token}/<entry>"
    title: str | None = None
    command: str  # the server command, for display
    port: int  # the in-container port it listens on


class ViewLiveStopped(_Body):
    """The View's live head was torn down (explicitly via close_view, or reaped with
    its idle session); the frontend drops the live iframe for this conversation."""

    type: Literal["view.live.stopped"] = "view.live.stopped"
    conversation_id: str


class ViewSnapshot(_Body):
    """A new **version** of the conversation's View — minted by a ``show``. It captures
    the agent's sandbox tree (the version's code, browsable + diffable via
    ``/views/snapshots/{snapshot_id}/…``) and how it previews: ``preview_artifact_id``
    + ``preview_kind`` point at the captured-bytes preview of a ``show(file=…)`` (fetch
    them from ``/views/{preview_artifact_id}/content``), or both are null for a
    live/auto preview (a running head, or the frontend auto-picks an entry HTML page).
    Additive to v1; no bump."""

    type: Literal["view.snapshot"] = "view.snapshot"
    conversation_id: str
    snapshot_id: str
    title: str | None = None
    created_at: datetime
    files_changed: int
    summary: str  # compact change tally, e.g. "+2 ~1 −0"
    preview_kind: str | None = None  # "html" | "image" | "text" | "other" | None
    preview_artifact_id: str | None = None


# --- Conversation ------------------------------------------------------------
class ConversationTitled(_Body):
    """The chassis named a freshly-created conversation from its first exchange,
    so the operator never has to. The title is persisted too; the frontend reveals
    it with a typing animation. Emitted mid-run (before ``run.ended``) so a still-
    open stream carries it. Additive to v1; no bump."""

    type: Literal["conversation.titled"] = "conversation.titled"
    conversation_id: str
    title: str


class ConversationCompacted(_Body):
    """The thread's earlier turns were folded into a summary before this turn ran,
    because its context footprint had reached the operator's threshold. Nothing was
    deleted — the transcript keeps every turn; this marks where the *model's* replayed
    view narrows to ``summary`` plus the turns after it. Emitted mid-run (before the
    answer streams) so a live client can drop the divider in as it happens, and
    persisted as its own message so a reload renders the same thing. Additive to v1;
    no bump."""

    type: Literal["conversation.compacted"] = "conversation.compacted"
    conversation_id: str
    # The checkpoint message the summary is stored on — the node the client renders
    # the divider against, and the same id a cold read returns.
    message_id: str
    summary: str
    # How many messages the summary stands in for, so the divider can say so without
    # the client counting anything itself.
    messages_compacted: int
    # What the fold cost, in coarse tokens: `tokens_before` over the messages that were
    # folded, `tokens_after` over the summary that replaced them. Both are the same
    # `estimate_tokens` text-only proxy the compaction trigger itself measures with — not
    # a provider's usage report — so a client should render them as approximate ("~62k →
    # ~4k"), never as billing figures. `services/conversation_view.py` recomputes the
    # identical three values for the cold-read compaction row, so a live divider and the
    # one a reload draws say the same thing.
    tokens_before: int = 0
    tokens_after: int = 0
    # The rendered turn the divider follows. A live client addresses turns, not tree
    # nodes, so the backend resolves the position rather than leaving the client to
    # approximate it and land somewhere a reload disagrees with. Null => append.
    after_message_id: str | None = None


# --- Notices -----------------------------------------------------------------
class CitationAdded(_Body):
    type: Literal["citation.added"] = "citation.added"
    url: str
    title: str | None = None


class ApprovalRequired(_Body):
    """A sensitive action is parked awaiting operator approval."""

    type: Literal["approval.required"] = "approval.required"
    tool_call_id: str
    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    summary: str
    # Plain-language description of what the action does and its effect, so the
    # operator can judge it without reading the raw arguments — set when the tool
    # supplies one (the host-execution path requires it). Additive to v1; no bump.
    explanation: str | None = None


class MessageQueued(_Body):
    """The operator sent a message while this run was still executing; it is
    queued for injection at the run's next model-request boundary. ``text`` rides
    inline so a reattaching client can rebuild the pending bubble purely from
    replay. Additive to v1; no bump."""

    type: Literal["message.queued"] = "message.queued"
    message_id: str
    text: str


class MessageEdited(_Body):
    """The operator rewrote a queued message's text before the run consumed it.
    ``text`` is the full replacement (not a delta), inline for the same reason as
    ``message.queued``'s: a reattaching client rebuilds the pending bubble purely
    from replay. Additive to v1; no bump."""

    type: Literal["message.edited"] = "message.edited"
    message_id: str
    text: str


class MessageWithdrawn(_Body):
    """The operator withdrew a queued message before the run consumed it.
    Additive to v1; no bump."""

    type: Literal["message.withdrawn"] = "message.withdrawn"
    message_id: str


class MessageInjected(_Body):
    """A queued message was handed to the model (emitted in drain order). From
    here on the message is part of the turn and will persist as a normal user
    message. Additive to v1; no bump."""

    type: Literal["message.injected"] = "message.injected"
    message_id: str


class PlanUpdated(_Body):
    """The agent's task list changed. Carries the **whole** list, not a delta: the stream
    is replayable from any seq, so full state is idempotent on replay and needs no ordering
    rules, and the list is small enough that the bytes don't matter. Each item is
    ``{id, content, status, active_form}`` with status one of pending/in_progress/
    completed/cancelled. Additive to v1; no bump."""

    type: Literal["plan.updated"] = "plan.updated"
    items: list[dict]


class LimitNotice(_Body):
    type: Literal["limit.notice"] = "limit.notice"
    # "steps" | "tool_calls" | "tokens" | "time" | "loop" | "verify" | "context" | "search"
    # ("context" = the model's context window was exceeded; the run stops, it isn't degraded.
    # "search" = deep research's two-empty-rounds abort.)
    limit: str
    message: str


EventBody = Annotated[
    RunStarted
    | RunMetrics
    | RunEnded
    | RunError
    | StepStarted
    | StepCompleted
    | ThinkingDelta
    | AnswerDelta
    | ToolStarted
    | ToolProgress
    | ToolCompleted
    | ToolFailed
    | CitationAdded
    | ViewLive
    | ViewLiveStopped
    | ViewSnapshot
    | ConversationTitled
    | ConversationCompacted
    | ApprovalRequired
    | MessageQueued
    | MessageEdited
    | MessageWithdrawn
    | MessageInjected
    | PlanUpdated
    | LimitNotice,
    Field(discriminator="type"),
]


@dataclass(frozen=True, slots=True)
class Event:
    """A stamped event: the producer's body plus the run-assigned seq/ts."""

    seq: int
    ts: datetime
    body: BaseModel

    def envelope(self) -> dict[str, Any]:
        """Flat ``{type, seq, ts, ...payload}`` dict — the on-the-wire shape."""
        data = self.body.model_dump(mode="json")
        data["seq"] = self.seq
        data["ts"] = self.ts.isoformat()
        return data

    def sse(self) -> str:
        """One SSE frame: ``id:`` carries seq for Last-Event-ID resume."""
        payload = json.dumps(self.envelope(), separators=(",", ":"))
        return f"id: {self.seq}\ndata: {payload}\n\n"
