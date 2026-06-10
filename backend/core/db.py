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
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine

# alembic.ini lives at the backend root (core/db.py is backend/core/db.py); its
# script_location is `%(here)s/migrations`, so resolution is cwd-independent.
_ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


def make_engine(url: str) -> Engine:
    """Build the SQLite engine. In-memory URLs share one connection (for tests)."""
    kwargs = {"connect_args": {"check_same_thread": False}}
    if ":memory:" in url:
        kwargs["poolclass"] = StaticPool
    engine = create_engine(url, **kwargs)

    # SQLite leaves foreign keys *off* per connection unless asked — without this
    # the declared FKs (e.g. Message → Conversation) enforce nothing, so a stray
    # conversation_id would silently orphan rows. Turn it on for every connection.
    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record):  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def init_db(engine: Engine) -> None:
    """Bring the schema to head via Alembic — applied automatically on startup,
    no manual step (XC-DATA-2).

    Migrations run against the **live engine** (handed to ``migrations/env.py`` on
    the Alembic config), not a fresh one built from a URL — essential for the
    in-memory test DBs, whose schema lives only on a single shared connection.
    """
    config = Config(str(_ALEMBIC_INI))
    config.attributes["connection"] = engine
    command.upgrade(config, "head")


async def in_session[T](engine: Engine, work: Callable[[Session], T]) -> T:
    """Run a unit of DB work in a threadpool and commit it."""

    def _run() -> T:
        with Session(engine, expire_on_commit=False) as session:
            result = work(session)
            session.commit()
            return result

    return await asyncio.to_thread(_run)
