"""Pillar III — the agent engine (Pydantic AI's Agent plus our meta-loop).

Within a turn we drive ``agent.iter()`` and translate its node stream into our
event protocol (Pillar II). Around it we will own the meta-loop: the deliverable
verifier (AE-1.4/AE-5.2), the loop-breaker (AE-5.1), history processors for
context reduction (AE-5.4), and FallbackModel (AE-5.3). RunDeps/RunContext carry
per-run policy and capability handles to the tools.

See docs/architecture/README.md (Pillar III) and decisions D3/D4/D5/D16/D20.
"""

from __future__ import annotations

from .deps import RunDeps
from .engine import build_chat_orchestrator
from .translate import stream_agent_run

__all__ = ["RunDeps", "build_chat_orchestrator", "stream_agent_run"]
