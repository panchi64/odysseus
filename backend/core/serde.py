"""Shared serialization helpers.

Lives in ``core`` so both the live translator (``agent/translate.py``) and the
static-history projection (``services/conversation_view.py``) can share the one
coercion without the lower layer importing the orchestrator.
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any


def _structure(value: Any) -> Any:
    """Recursively unwrap dataclasses/datetimes into plain JSON-able structures.
    A tool may return a dataclass (or a list/dict of them) — e.g. `SearchResult` —
    and losing that structure to `str(value)` would make the persisted result
    unusable to any downstream reader (the frontend's cold-reload citation
    derivation among them)."""
    if is_dataclass(value) and not isinstance(value, type):
        return _structure(asdict(value))
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _structure(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_structure(v) for v in value]
    return value


def jsonable(value: Any) -> Any:
    """Coerce a tool result into something the JSON envelope can carry.

    Never raises: the whole coercion — the ``_structure`` pre-pass included — sits under
    the guard, so a value that can't be structured or serialized (a reference cycle blowing
    the recursion limit, a non-deepcopyable dataclass field) degrades to ``str(value)``
    rather than crashing tool-result serialization for the turn."""
    try:
        structured = _structure(value)
        json.dumps(structured)
        return structured
    except Exception:  # noqa: BLE001 — total fallback: any coercion failure degrades to str
        return str(value)
