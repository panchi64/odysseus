"""Database engine and the sync-in-threadpool access pattern.

Persistence runs on **plain SQLite** for now. The connection is built in one
place (:func:`make_engine`) so at-rest encryption can swap in here later — once
auth exists to derive a key from — without touching any caller. SQLite's driver
is synchronous, so every unit of DB work runs in a thread to keep the event loop
free, and genuinely parallelizes (SQLite releases the GIL during I/O).
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from pathlib import Path
from weakref import WeakKeyDictionary

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine

# In-memory engines share a single connection (StaticPool), which is *not* safe for
# the concurrent, multi-threaded access `in_session` produces (each call runs on its
# own threadpool thread). A per-engine lock serializes their sessions so two threads
# never drive the one connection at once. File-backed engines hand each thread its
# own connection and carry no lock, so they run fully unserialized.
_CONN_LOCKS: WeakKeyDictionary[Engine, threading.Lock] = WeakKeyDictionary()

# alembic.ini lives at the backend root (core/db.py is backend/core/db.py); its
# script_location is `%(here)s/migrations`, so resolution is cwd-independent.
_ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


def make_engine(url: str) -> Engine:
    """Build the SQLite engine. In-memory URLs share one connection (for tests)."""
    kwargs = {"connect_args": {"check_same_thread": False}}
    if ":memory:" in url:
        kwargs["poolclass"] = StaticPool
    engine = create_engine(url, **kwargs)

    # A single-connection (in-memory) engine must serialize its threadpool sessions;
    # see `_CONN_LOCKS`. File-backed engines pool a connection per thread and skip it.
    if ":memory:" in url:
        _CONN_LOCKS[engine] = threading.Lock()

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
    """Run a unit of DB work in a threadpool and commit it. For a single-connection
    in-memory engine the session is taken under that engine's lock, so overlapping
    threadpool calls never drive the one shared connection at the same time."""
    lock = _CONN_LOCKS.get(engine)

    def _run() -> T:
        with Session(engine, expire_on_commit=False) as session:
            result = work(session)
            session.commit()
            return result

    def _run_guarded() -> T:
        if lock is None:
            return _run()
        with lock:
            return _run()

    return await asyncio.to_thread(_run_guarded)
