"""Pillar III — the agent engine (Pydantic AI's Agent plus our meta-loop).

Within a turn we drive ``agent.iter()`` and translate its node stream into our
event protocol. Around it we own the meta-loop: the deliverable verifier
(AE-1.4/AE-5.2), the loop-breaker (AE-5.1), history processors for context
reduction (AE-5.4), and FallbackModel (AE-5.3). RunDeps/RunContext carry
per-run policy and capability handles.

Stub — no implementation yet. See docs/architecture/README.md (Pillar III).
"""
