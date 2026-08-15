"""RunDeps — the per-run dependency object the agent hands to its tools.

Lives in ``tools/`` because it is the agent↔tools contract and ``tools`` sits
below ``agent`` in the dependency order (agent → tools → services → core), so
both layers import it without a cycle. It becomes ``RunContext.deps`` inside
Pydantic AI: a tool reaches the Run (to emit its own ``tool.progress`` events),
the owner, the per-run enabled-tool policy, and — through ``caps`` — every
capability handle, never via globals.

``caps`` is the **agent-facing capability bag**: a typed container each feature
manifest exports its tool-reachable services into (``FeatureRuntime.capabilities``),
assembled once at startup. A tool resolves its capability with
``ctx.deps.caps.get_optional(SomeStore)`` and **degrades** — returns an
"unavailable" result — when the handle is absent; a new capability is one export
on its own manifest, never a new field here or a new argument at any call site.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.container import ServiceContainer
from runs import Run


@dataclass
class CompactionContext:
    """Per-run tool-result compaction state, reached by both the history processor (which
    fills it) and the ``expand_tool_result`` tool (which reads it). Lives here in ``tools/``
    because it is part of the deps contract; the processor that drives it lives in ``agent/``.

    ``enabled``/``keep_recent``/``min_tokens`` are the resolved effective config for the turn
    (operator default, or a per-conversation override). ``protect_from`` is the turn's
    persistence index — messages at or after it are the current turn (never compacted, since
    they are exactly what the engine persists); only earlier messages are eligible. The engine
    sets it once the conversation history length is known; 0 ⇒ nothing is prior (a safe no-op).
    ``full_by_id`` maps a compacted tool call's id → its original, full content, so the
    rehydration tool can return it verbatim — populated by the processor, which always sees the
    full DB history before condensing it."""

    enabled: bool = False
    keep_recent: int = 6
    min_tokens: int = 0
    protect_from: int = 0
    full_by_id: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunDeps:
    run: Run
    owner_id: str
    # The capability handles this run's tools may reach (see the module docstring).
    # Empty ⇒ every capability-backed tool degrades — the same contract as a single
    # missing handle, applied uniformly.
    caps: ServiceContainer = field(default_factory=ServiceContainer)
    # Operator-disabled tools, by namespaced name. Empty ⇒ all enabled.
    disabled_tools: frozenset[str] = field(default_factory=frozenset)
    conversation_id: str | None = None
    # Tool-result compaction state for this turn — the history processor fills its handle
    # map; the `expand_tool_result` tool reads it. None ⇒ compaction is off for the run.
    compaction: CompactionContext | None = None

    @property
    def sandbox_key(self) -> str:
        """The key a conversation's sandbox session and its artifacts share — the
        conversation when there is one, else the run (a stateless turn). Defined
        once so the code and preview tools can never key them differently."""
        return self.conversation_id or self.run.id
