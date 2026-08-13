"""External tools — MCP servers + third-party connectors (`MCP-*`, `INTEG-*`, `AE-3.6`)
— **reserved stub**, filled in by the external tools track (T3).

See ``tools/mail.py`` for why the category is registered before it exists.

Two notes for the track that fills this in:

- **Do not hand-roll an MCP client.** Pydantic AI ships ``MCPServerStdio`` /
  ``MCPServerSSE`` / ``MCPServerStreamableHTTP``, which are ``AbstractToolset`` subclasses
  and compose directly into the stack in ``toolsets.py``. The operator's per-tool
  enable/disable (`MCP-2`) then falls out of the existing ``_enabled_gate`` for free.
- **External tools are sensitive by default.** They are the case the `AE-3` sensitivity
  model cannot enumerate, so they gate until the operator marks a specific tool trusted —
  per tool, never per server. That is a *runtime-conditional* gate, so follow the shape in
  ``tools/recall_gate.py`` (raise ``ApprovalRequired`` unless ``ctx.tool_call_approved``),
  not the static ``requires_approval=True`` marking.
"""

from __future__ import annotations

from pydantic_ai import FunctionToolset

from .deps import RunDeps


def external_toolset() -> FunctionToolset[RunDeps]:
    """The external-tool category — empty until T3 lands."""
    toolset: FunctionToolset[RunDeps] = FunctionToolset()
    return toolset
