"""RunDeps — the per-run dependency object the agent hands to its tools.

Lives in ``tools/`` because it is the agent↔tools contract and ``tools`` sits
below ``agent`` in the dependency order (agent → tools → services → core), so
both layers import it without a cycle. It becomes ``RunContext.deps`` inside
Pydantic AI: a tool reaches the Run (to emit its own ``tool.progress`` events),
the owner, and the per-run enabled-tool policy through it — never via globals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from runs import Run

if TYPE_CHECKING:
    from services.memory import MemoryStore


@dataclass
class RunDeps:
    run: Run
    owner_id: str
    # Operator-disabled tools, by namespaced name. Empty ⇒ all enabled.
    disabled_tools: frozenset[str] = field(default_factory=frozenset)
    # Capability handles the tools reach (never via globals). More land here as
    # their services do (search, the open document, …).
    memory: MemoryStore | None = None
