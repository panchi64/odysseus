"""RunDeps — the per-run dependency object handed to the agent and its tools.

Becomes ``RunContext.deps`` inside Pydantic AI, so a tool can reach the Run (to
emit its own ``tool.progress`` events), the owner, and — as they land —
capability handles, the enabled-tool policy, and any open document. Keeping
these on deps (not globals) is what lets the toolset stack key access decisions
on the current run.
"""

from __future__ import annotations

from dataclasses import dataclass

from runs import Run


@dataclass
class RunDeps:
    run: Run
    owner_id: str
    # Future: capability handles, enabled-tool set, open document (D14/AE-4.2).
