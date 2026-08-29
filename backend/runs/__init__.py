"""Pillar I + II — the Run substrate and the event protocol (the chassis).

A Run is one server-side, background-executing unit of work for one request.
Chat, agent, and research all ride it, so continuity, resume, cancellation,
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
    PROTOCOL_VERSION,
    AnswerDelta,
    ApprovalRequired,
    CitationAdded,
    ContextComposition,
    ContextThresholds,
    ContextWindow,
    ConversationCompacted,
    ConversationTitled,
    Event,
    EventBody,
    LimitNotice,
    MessageInjected,
    MessageQueued,
    MessageWithdrawn,
    PlanUpdated,
    RunEnded,
    RunError,
    RunMetrics,
    RunStarted,
    StepCompleted,
    StepStarted,
    ThinkingDelta,
    ToolCompleted,
    ToolFailed,
    ToolProgress,
    ToolStarted,
    ViewLive,
    ViewLiveStopped,
    ViewSnapshot,
)
from .overhead import TurnOverhead
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
    "CitationAdded",
    "ViewLive",
    "ViewLiveStopped",
    "ViewSnapshot",
    "ConversationCompacted",
    "ConversationTitled",
    "ApprovalRequired",
    "MessageQueued",
    "MessageWithdrawn",
    "MessageInjected",
    "PlanUpdated",
    "LimitNotice",
]
