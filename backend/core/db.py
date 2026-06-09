"""Database engine and the sync-in-threadpool access pattern.

Persistence runs on **plain SQLite** for now. The connection is built in one
place (:func:`make_engine`) so at-rest encryption can swap in here later — once
auth exists to derive a key from — without touching any caller. SQLite's driver
is synchronous, so every unit of DB work runs in a thread to keep the event loop
free, and genuinely parallelizes (SQLite releases the GIL during I/O).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from sqlalchemy import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine


def make_engine(url: str) -> Engine:
    """Build the SQLite engine. In-memory URLs share one connection (for tests)."""
    kwargs = {"connect_args": {"check_same_thread": False}}
    if ":memory:" in url:
        kwargs["poolclass"] = StaticPool
    return create_engine(url, **kwargs)


def init_db(engine: Engine) -> None:
    """Create tables. Alembic migrations replace this with the encryption pass."""
    import models.conversation  # noqa: F401 — register tables on the metadata

    SQLModel.metadata.create_all(engine)


async def in_session[T](engine: Engine, work: Callable[[Session], T]) -> T:
    """Run a unit of DB work in a threadpool and commit it."""

    def _run() -> T:
        with Session(engine, expire_on_commit=False) as session:
            result = work(session)
            session.commit()
            return result

    return await asyncio.to_thread(_run)
