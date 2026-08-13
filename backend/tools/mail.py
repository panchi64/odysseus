"""Mail tools (`EMAIL-*`) — **reserved stub**, filled in by the mail track (T1).

Registered in ``toolsets.py`` from this commit so the parallel sprint tracks never contend
for ``default_categories()``. Empty until its track lands: an empty category contributes no
tool names, so the catalog the model sees is unchanged.

When filled in, note that **sending or replying is a sensitive action** and must carry
``requires_approval=True`` (`AE-3.1`), and every fetched message body must be run through
``core.untrusted.wrap_untrusted`` before it can reach the model (`XC-SEC-5`).
"""

from __future__ import annotations

from pydantic_ai import FunctionToolset

from .deps import RunDeps


def mail_toolset() -> FunctionToolset[RunDeps]:
    """The mail category — empty until T1 lands."""
    toolset: FunctionToolset[RunDeps] = FunctionToolset()
    return toolset
