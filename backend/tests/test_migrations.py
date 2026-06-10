"""Schema is brought to head by Alembic on startup (no manual step)."""

from __future__ import annotations

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlmodel import Session

from core.db import _ALEMBIC_INI, init_db, make_engine


def _head_revision() -> str:
    script = ScriptDirectory.from_config(Config(str(_ALEMBIC_INI)))
    head = script.get_current_head()
    assert head is not None
    return head


def test_init_db_creates_all_tables_at_head():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)

    tables = set(inspect(engine).get_table_names())
    # Every model's table, plus Alembic's own version bookkeeping.
    assert {"conversations", "messages", "model_endpoints", "model_roles"} <= tables
    assert "alembic_version" in tables


def test_init_db_stamps_the_head_revision():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)

    with Session(engine) as session:
        stamped = session.exec(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert stamped == _head_revision()


def test_init_db_is_idempotent():
    # Re-running against an already-migrated DB is a no-op, not an error — the
    # startup path runs unconditionally every boot.
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    init_db(engine)
    assert "conversations" in set(inspect(engine).get_table_names())
