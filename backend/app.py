"""FastAPI application assembly — the slim orchestrator.

Build the app, install middleware, wire auth, register routers, and hang shared
singletons (the run registry, capability handles) on ``app.state``. Business
logic lives below this layer; this file delegates. Pydantic AI is the engine,
this is the chassis — see ``docs/architecture/README.md``.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import Settings, get_settings
from core.db import init_db, make_engine
from routes import chat, health, runs
from runs import RunRegistry
from services.conversations import ConversationStore


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Process-lifetime startup/shutdown.

    Brings up the run registry and the persistence store (DB engine + schema +
    write-behind drainer). Shutdown flushes pending writes. Capability handles
    (``services/``) wire in here as they land.
    """
    settings: Settings = app.state.settings
    app.state.runs = RunRegistry(
        max_concurrency=settings.run_max_concurrency,
        wall_clock_timeout_s=settings.run_wall_clock_timeout_s,
        inactivity_timeout_s=settings.run_inactivity_timeout_s,
    )

    url = settings.db_url
    if url is None:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{settings.data_dir / 'app.db'}"
    engine = make_engine(url)
    init_db(engine)
    app.state.db_engine = engine
    app.state.conversations = ConversationStore(engine)
    await app.state.conversations.start()
    try:
        yield
    finally:
        await app.state.conversations.stop()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Odysseus", version=settings.version, lifespan=lifespan)
    app.state.settings = settings  # the lifespan reads this (tests inject it)

    # Origin-agnostic API: the backend makes no assumption about who serves the
    # frontend. CORS is configurable; bearer auth works same- or split-origin.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(runs.router)
    app.include_router(chat.router)
    return app


app = create_app()
