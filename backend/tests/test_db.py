"""core.db engine configuration: the per-connection PRAGMAs `make_engine` installs."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from core.db import _BUSY_TIMEOUT_MS, make_engine


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
