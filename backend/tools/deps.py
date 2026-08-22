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

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from pydantic_ai import RunContext

from core.container import ServiceContainer
from runs import Run


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

    @property
    def sandbox_key(self) -> str:
        """The key a conversation's sandbox session and its artifacts share — the
        conversation when there is one, else the run (a stateless turn). Defined
        once so the code and preview tools can never key them differently."""
        return self.conversation_id or self.run.id


# A feature-contributed dynamic instruction (a manifest's `instructions` export): the
# engine registers each on the agent, it re-resolves fresh every turn, reaches its
# capability through the run's bag, and returns "" to no-op when the capability is
# absent. Part of the deps contract for the same reason `RunDeps` is — both the engine
# and the feature layer must name the shape without a cycle.
type InstructionProvider = Callable[[RunContext[RunDeps]], Awaitable[str]]

# A feature-contributed per-turn context block (a manifest's `prompt_context` export):
# like an InstructionProvider it re-resolves fresh each turn and is never persisted, but
# the engine delivers it at the *tail* of the current turn's user prompt instead of the
# instructions block at the head of the request — volatile content at the head would
# invalidate the inference engine's prompt-prefix cache from byte 0 on every change,
# while a tail part leaves the whole history byte-stable. Called outside a live run
# (before the agent starts), so it takes the raw handles rather than a RunContext:
# (caps, owner_id, conversation_id) → text, "" to no-op.
type PromptContextProvider = Callable[
    [ServiceContainer, str, str | None], Awaitable[str]
]
