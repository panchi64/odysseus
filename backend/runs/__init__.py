"""Pillar I + II — the Run substrate and the event protocol (the chassis).

A Run is one server-side, background-executing unit of work for one request.
Chat and agent work both ride it, so continuity, resume, cancellation,
timeouts, and metrics are written once here and inherited everywhere.

- :class:`RunRegistry` — launch/track/bound/cancel Runs (in-process asyncio).
- :class:`Run` / :class:`RunStatus` — the unit of work and its lifecycle.
- :class:`RunStream` — per-run event buffer + broker (resume via Last-Event-ID).
- ``events`` — the frozen v1 typed event union.
- :func:`sse_response` — stream a Run to a client over SSE.

See docs/architecture/README.md (Pillars I & II).
"""

from __future__ import annotations

from . import events
from .events import (
    DEFAULT_CONTEXT_THRESHOLDS,
    INJECTED_TEXT_LIMIT,
    PROTOCOL_VERSION,
    AnswerDelta,
    ApprovalRequired,
    BrowserLive,
    CitationAdded,
    ContextComposition,
    ContextInjected,
    ContextSegment,
    ContextThresholds,
    ContextWindow,
    ConversationCompacted,
    ConversationLinked,
    ConversationTitled,
    Event,
    EventBody,
    LastRequestUsage,
    LimitNotice,
    MessageInjected,
    MessageQueued,
    MessageWithdrawn,
    PlanUpdated,
    ReviewCompleted,
    ReviewStarted,
    RunEnded,
    RunError,
    RunMetrics,
    RunStarted,
    StepCompleted,
    StepStarted,
    ThinkingDelta,
    ToolCompleted,
    ToolFailed,
    ToolImage,
    ToolProgress,
    ToolStarted,
    ViewLive,
    ViewLiveStopped,
    ViewSnapshot,
)
from .overhead import BriefBlock, ToolGroupOverhead, TurnOverhead
from .registry import ConversationBusyError, RunRegistry, RunTimeout
from .run import Orchestrator, QueuedMessage, Run, RunStatus
from .stream import RunStream
from .timings import ResponseTiming, TimingTotals, TurnTimer, total_timings
from .transport import parse_last_event_id, sse_response

__all__ = [
    "events",
    "PROTOCOL_VERSION",
    "Event",
    "EventBody",
    "RunRegistry",
    "RunTimeout",
    "ConversationBusyError",
    "Run",
    "RunStatus",
    "QueuedMessage",
    "Orchestrator",
    "RunStream",
    "BriefBlock",
    "ToolGroupOverhead",
    "TurnOverhead",
    "TurnTimer",
    "ResponseTiming",
    "TimingTotals",
    "total_timings",
    "sse_response",
    "parse_last_event_id",
    # event bodies (re-exported for producers)
    "RunStarted",
    "RunMetrics",
    "DEFAULT_CONTEXT_THRESHOLDS",
    "ContextComposition",
    "ContextSegment",
    "LastRequestUsage",
    "ContextThresholds",
    "ContextWindow",
    "RunEnded",
    "RunError",
    "StepStarted",
    "StepCompleted",
    "ThinkingDelta",
    "AnswerDelta",
    "ToolStarted",
    "ToolProgress",
    "ToolCompleted",
    "ToolFailed",
    "ToolImage",
    "CitationAdded",
    "ViewLive",
    "ViewLiveStopped",
    "ViewSnapshot",
    "BrowserLive",
    "ConversationCompacted",
    "ConversationLinked",
    "ConversationTitled",
    "ContextInjected",
    "INJECTED_TEXT_LIMIT",
    "ApprovalRequired",
    "ReviewStarted",
    "ReviewCompleted",
    "MessageQueued",
    "MessageWithdrawn",
    "MessageInjected",
    "PlanUpdated",
    "LimitNotice",
]
