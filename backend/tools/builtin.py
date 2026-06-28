"""Built-in utility tools — the minimal starter category.

Real capabilities (memory, web, email, shell, …) arrive as their services land;
each becomes a thin tool over a ``services/`` capability. This category exists
so the toolset stack has something to compose and gate today.
"""

from __future__ import annotations

import json

from pydantic_ai import FunctionToolset, ModelRetry, RunContext

from core.serde import jsonable
from runs.events import now_utc

from .deps import RunDeps


def builtin_toolset() -> FunctionToolset[RunDeps]:
    toolset: FunctionToolset[RunDeps] = FunctionToolset()

    @toolset.tool_plain
    def now() -> str:
        """Return the current date and time in UTC (ISO 8601)."""
        return now_utc().isoformat()

    @toolset.tool
    def expand_tool_result(ctx: RunContext[RunDeps], tool_call_id: str) -> str:
        """Return the full, original output of an earlier tool call that was condensed in the
        history. Pass the tool_call_id shown in a "[tool output compacted — … call
        builtin_expand_tool_result("<id>") …]" marker. Use this only when the notice isn't
        enough — the full output is large."""
        cc = ctx.deps.compaction
        full = cc.full_by_id.get(tool_call_id) if cc is not None else None
        if full is None:
            raise ModelRetry(
                f"No compacted tool result with id {tool_call_id!r}. Use the exact id from a "
                '"[tool output compacted …]" marker in the history.'
            )
        # Structured originals (dict/list) come back as JSON so the model reads them faithfully,
        # not as a Python repr.
        return full if isinstance(full, str) else json.dumps(jsonable(full), ensure_ascii=False)

    return toolset
