"""Shared test helpers: a booted app + client, and an SSE event collector."""

from __future__ import annotations

import json
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from pydantic_ai.models.test import TestModel

from app import create_app
from core.config import Settings


def patch_model_resolution(monkeypatch, *, output_text: str = "hi", call_tools=()):
    """Point registry resolution at a ``TestModel`` so route tests run without a live
    model server. One patch covers every caller: ``resolve_detailed`` is the single
    entry point that builds a chat model, and ``resolve_background`` delegates to it,
    so the chat route's ``main`` and the background (verify/title) model both come
    through here. ``call_tools=()`` keeps it a plain text turn — the default catalog
    has an approval-gated tool that would otherwise park the run."""
    from services.registry import ModelRegistry, ResolvedModel

    def _model() -> TestModel:
        return TestModel(custom_output_text=output_text, call_tools=list(call_tools))

    async def resolve_detailed(self, role, **kwargs):
        return ResolvedModel(model=_model(), reasoning_off={})

    monkeypatch.setattr(ModelRegistry, "resolve_detailed", resolve_detailed)


async def granting_store(owner: str, conv: str, *tool_names: str, ttl_s: float = 3600):
    """An ``ApprovalGrantStore`` on a throwaway DB that pre-grants ``tool_names`` in
    ``conv``. Lets a ``TestModel``-driven wiring test (which calls every offered tool)
    drive an AE-3.8-gated recall tool through to its service — the active grant makes the
    engine auto-approve it inline instead of parking on the approval prompt."""
    from core.db import init_db, make_engine
    from services.approval_grants import ApprovalGrantStore

    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    store = ApprovalGrantStore(engine, ttl_s)
    for name in tool_names:
        await store.grant(owner, conv, name)
    return store


def swap_tool_catalog(app, categories) -> None:
    """Replace the booted app's assembled tool catalog **in place**. The mapping is one
    shared object — the chat route, the approval-resume path, and the scheduler's
    executor all hold the same dict the app assembled — so mutating its contents (not
    rebinding `app.state.tool_categories`) is what reaches every path."""
    app.state.tool_categories.clear()
    app.state.tool_categories.update(categories)


def full_tool_categories():
    """The complete category mapping a real app assembles — core plus every manifest's
    `toolsets` export, via the same discovery the app uses — for tests that measure
    the whole catalog without booting an app."""
    from harness.discovery import discover_manifests
    from tools.toolsets import core_categories

    categories = core_categories()
    for manifest in discover_manifests():
        for name, factory in manifest.toolsets:
            categories[name] = factory()
    return categories


@asynccontextmanager
async def client_app(*, auth_enabled: bool = False, passphrase: str | None = "test-passphrase"):
    """A booted app + async client, backed by a throwaway in-memory DB.

    An in-memory SQLite URL plus a temp data dir (for the keyfile) keep tests off
    the real ``data/`` dir. By default auth is off and a passphrase unlocks the
    vault at boot, so feature endpoints are reachable without a token; the auth
    tests pass ``auth_enabled=True, passphrase=None`` to exercise setup/login.
    """
    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(
            db_url="sqlite:///:memory:",
            data_dir=Path(tmp),
            # Coding-mode worktrees live *outside* `data_dir` by design (the host-command
            # fence denies reads of the whole data directory), so they need their own
            # redirect here or a test cuts real git worktrees into the operator's home.
            worktrees_dir=Path(tmp) / "worktrees",
            auth_enabled=auth_enabled,
            unlock_passphrase=passphrase,
            # No container side effects in tests, regardless of the host: the managed
            # SearXNG / web-fetch browser would pull/launch a container at boot, and
            # sandbox detection would otherwise flip with host Docker. Tests that need
            # any of these inject it directly (e.g. app.state.sandbox = a fake).
            searxng_enabled=False,
            web_fetch_enabled=False,
            sandbox_enabled=False,
            # Assume online without touching the network, so the offline-mode monitor's
            # boot probe doesn't make a real connection (and the web rows stay nominal).
            offline_check_enabled=False,
        )
        app = create_app(settings)
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                yield client, app


async def collect_sse_events(client, run_id, *, last_event_id=None):
    """Drain a run's SSE stream to a list of decoded event envelopes."""
    params = {} if last_event_id is None else {"last_event_id": last_event_id}
    events = []
    async with client.stream("GET", f"/runs/{run_id}/events", params=params) as resp:
        assert resp.status_code == 200
        async for line in resp.aiter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[len("data:") :].strip()))
    return events
