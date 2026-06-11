"""Shared serialization helpers.

Lives in ``core`` so both the live translator (``agent/translate.py``) and the
static-history projection (``services/conversation_view.py``) can share the one
coercion without the lower layer importing the orchestrator.
"""

from __future__ import annotations

import json
from typing import Any


def jsonable(value: Any) -> Any:
    """Coerce a tool result into something the JSON envelope can carry."""
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)
