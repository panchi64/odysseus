"""Tools — thin adapters over services/, exposed to the model as toolsets.

Which tools a run sees is *our* policy: a namespaced, enabled-gated toolset
stack (``toolsets.py``) keyed on the run's :class:`RunDeps`. Sensitive tools
pause for operator approval at execution, not filtered out. Logic never lives in
a tool — it delegates to a capability in ``services/``.

See docs/architecture/README.md (Pillar III, §2.2).
"""

from __future__ import annotations

from .builtin import builtin_toolset
from .deps import Capabilities, RunDeps
from .toolsets import build_agent_toolsets, default_categories

__all__ = [
    "Capabilities",
    "RunDeps",
    "builtin_toolset",
    "build_agent_toolsets",
    "default_categories",
]
