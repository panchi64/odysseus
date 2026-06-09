"""Pillar I — the Run substrate (the chassis).

A Run is one server-side, background-executing unit of work for one request.
This package will own the RunRegistry, the in-process event broker, the
sequence-numbered event buffer (disconnect/resume — AE-7), the lifecycle state
machine (queued → running → {done|blocked|error|cancelled}, with awaiting_input
for approvals — D20), bounds/timeouts, and the SSE transport. Chat, agent, and
research all ride it.

Stub — no implementation yet. See docs/architecture/README.md (Pillar I).
"""
