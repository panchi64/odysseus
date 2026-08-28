"""core.db engine configuration: the per-connection PRAGMAs `make_engine` installs."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text
from sqlmodel import Session

from core.db import _BUSY_TIMEOUT_MS, get_owned, in_session, init_db, make_engine
from core.exceptions import NotFoundError
from models.memory import Memory


def test_file_backed_connections_get_the_busy_timeout(tmp_path: Path):
    """The connect handler must arm SQLite's busy handler on every pooled connection —
    without it, two threadpool sessions colliding on the single write lock turn a
    microseconds-long overlap into an immediate `database is locked` (the scheduler
    double-fire regression's root cause)."""
    engine = make_engine(f"sqlite:///{tmp_path / 'app.db'}")
    with engine.connect() as connection:
        value = connection.execute(text("PRAGMA busy_timeout")).scalar_one()
    assert value == _BUSY_TIMEOUT_MS

    # The handler fires per *connect*, not once per engine — a genuinely fresh
    # DBAPI connection (the pool's is discarded) must come armed the same way.
    engine.dispose()
    with engine.connect() as connection:
        value = connection.execute(text("PRAGMA busy_timeout")).scalar_one()
    assert value == _BUSY_TIMEOUT_MS


def test_foreign_keys_are_on_per_connection(tmp_path: Path):
    engine = make_engine(f"sqlite:///{tmp_path / 'app.db'}")
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1


# --- the owner-scoped single-row read every store shares ----------------------
async def test_get_owned_answers_identically_for_missing_and_foreign_rows():
    # The whole point of the ownership check: distinguishing "not yours" from "doesn't
    # exist" confirms to a caller that an id it guessed is real. Every store's read of a
    # single row crosses this boundary, so the two must be indistinguishable.
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)

    def insert(session: Session) -> str:
        memory = Memory(owner_id="someone-else", content_enc=b"x")
        session.add(memory)
        session.flush()
        return memory.id

    foreign_id = await in_session(engine, insert)

    with pytest.raises(NotFoundError) as foreign:
        await get_owned(engine, Memory, foreign_id, "operator", what="memory")
    with pytest.raises(NotFoundError) as missing:
        await get_owned(engine, Memory, "no-such-id", "operator", what="memory")

    assert str(foreign.value) == f"memory {foreign_id!r} not found"
    assert str(missing.value) == "memory 'no-such-id' not found"


async def test_get_owned_returns_the_row_for_its_owner():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)

    def insert(session: Session) -> str:
        memory = Memory(owner_id="operator", content_enc=b"x")
        session.add(memory)
        session.flush()
        return memory.id

    memory_id = await in_session(engine, insert)

    row = await get_owned(engine, Memory, memory_id, "operator", what="memory")
    assert row.id == memory_id and row.owner_id == "operator"
