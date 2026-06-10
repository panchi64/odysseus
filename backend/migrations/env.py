"""Alembic environment.

Two ways in:

- **Runtime (startup auto-upgrade).** ``core.db.init_db`` puts the live engine on
  ``config.attributes['connection']`` and calls ``command.upgrade(..., 'head')``.
  We migrate on *that* engine — crucial for the in-memory test DBs, whose schema
  lives only on a single shared connection.
- **CLI (autogenerate / manual).** No connection is attached, so we build one
  from ``sqlalchemy.url`` (``alembic.ini``, overridable via ``ODYSSEUS_DB_URL``).

``target_metadata`` is the SQLModel registry, populated by importing every model
module, so ``--autogenerate`` sees the full schema. SQLite gets batch mode, since
several ``ALTER`` shapes require the table-rebuild dance there.
"""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import Engine, create_engine
from sqlmodel import SQLModel

# Import every model module so its tables register on SQLModel.metadata.
import models.conversation  # noqa: F401
import models.registry  # noqa: F401

config = context.config
target_metadata = SQLModel.metadata


def _run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,  # SQLite-safe ALTERs (table-rebuild under the hood)
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    attached = config.attributes.get("connection")
    if attached is not None:
        # A live engine or connection handed in by the app at startup.
        if isinstance(attached, Engine):
            with attached.connect() as connection:
                _run(connection)
        else:
            _run(attached)
        return

    url = os.environ.get("ODYSSEUS_DB_URL") or config.get_main_option("sqlalchemy.url")
    engine = create_engine(url)
    with engine.connect() as connection:
        _run(connection)


def run_migrations_offline() -> None:
    """Emit SQL without a DBAPI connection (``alembic upgrade --sql``)."""
    url = os.environ.get("ODYSSEUS_DB_URL") or config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
