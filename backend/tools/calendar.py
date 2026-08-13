"""Calendar tools (`CAL-*`) — **reserved stub**, filled in by the calendar track (T2).

See ``tools/mail.py`` for why the category is registered before it exists.
"""

from __future__ import annotations

from pydantic_ai import FunctionToolset

from .deps import RunDeps


def calendar_toolset() -> FunctionToolset[RunDeps]:
    """The calendar category — empty until T2 lands."""
    toolset: FunctionToolset[RunDeps] = FunctionToolset()
    return toolset
