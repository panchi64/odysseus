"""Regression tests for research route ownership gates.

Pins the fix for the spinoff endpoint, which previously only required an
authenticated user (not ownership). Any logged-in user could spin off a new
chat session pre-seeded with ANOTHER user's full research report by passing
that report's session_id — a cross-user data disclosure. The gate must reject
a non-owner with 404 (not 403, so the report's existence isn't leaked).
"""

import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# Stub the lazily/eagerly imported deps so `routes.research_routes` imports
# cleanly under the conftest's heavy-dep mocks (see tests/CLAUDE.md).
for _stub, _attrs in {
    "core.database": {"SessionLocal": MagicMock(), "ModelEndpoint": MagicMock()},
    "src.endpoint_resolver": {
        "resolve_endpoint": MagicMock(return_value=("", "", {})),
        "normalize_base": MagicMock(),
        "build_chat_url": MagicMock(),
        "build_headers": MagicMock(),
    },
}.items():
    if _stub not in sys.modules:
        m = types.ModuleType(_stub)
        for k, v in _attrs.items():
            setattr(m, k, v)
        sys.modules[_stub] = m

from fastapi import HTTPException
from routes.research_routes import setup_research_routes


def _spinoff_endpoint(research_handler, session_manager):
    """Pull the spinoff route's handler out of the assembled router."""
    router = setup_research_routes(research_handler, session_manager=session_manager)
    for route in router.routes:
        if getattr(route, "path", "") == "/api/research/spinoff/{session_id}":
            return route.endpoint
    raise AssertionError("spinoff route not registered")


def _request_for(user):
    return SimpleNamespace(state=SimpleNamespace(current_user=user))


async def test_spinoff_rejects_non_owner():
    # Research session owned by bob, living in the in-memory task registry.
    handler = MagicMock()
    handler._active_tasks = {"rp-abc": {"owner": "bob"}}
    spinoff = _spinoff_endpoint(handler, session_manager=MagicMock())

    with pytest.raises(HTTPException) as exc:
        await spinoff("rp-abc", _request_for("alice"))
    assert exc.value.status_code == 404
    # Must NOT touch the result / create a session for a non-owner.
    handler.get_result.assert_not_called()


async def test_spinoff_requires_authentication():
    handler = MagicMock()
    handler._active_tasks = {}
    spinoff = _spinoff_endpoint(handler, session_manager=MagicMock())

    with pytest.raises(HTTPException) as exc:
        await spinoff("rp-abc", _request_for(None))
    assert exc.value.status_code == 401
