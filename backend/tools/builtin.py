"""Built-in utility tools — the minimal starter category.

Real capabilities (memory, web, email, shell, …) arrive as their services land;
each becomes a thin tool over a ``services/`` capability. This category exists
so the toolset stack has something to compose and gate today.
"""

from __future__ import annotations

from pydantic_ai import FunctionToolset

from runs.events import now_utc

from .deps import RunDeps


def builtin_toolset() -> FunctionToolset[RunDeps]:
    toolset: FunctionToolset[RunDeps] = FunctionToolset()

    @toolset.tool_plain
    def now() -> str:
        """Return the current date and time in UTC (ISO 8601)."""
        return now_utc().isoformat()

    return toolset
