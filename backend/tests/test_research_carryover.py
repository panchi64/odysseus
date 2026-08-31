"""The operator's old research rows survive the entity being retired.

Research was a row with a question and a finished report. It is a conversation now, and
the migration that drops the table runs unattended at startup against the live database —
so a drop that took the rows with it would be a silent, unrecoverable deletion of hours of
reading the operator asked for. Two halves have to hold, and both fail quietly:

- the **migration** copies every row out before it drops the table, in the one revision,
  and puts them back on the way down;
- the **seeding** turns each carried row into a thread that actually opens — which is the
  part a migration cannot do, because a message is sealed with the vault and schema
  upgrades run before unlock with no key.

Every migration here runs against a throwaway file database with ``ODYSSEUS_DB_URL``
pointed at it. ``alembic.ini`` defaults to the *live* ``data/app.db``, so running one of
these unset would migrate the operator's own database.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlmodel import Session

import harness.manifests.research as research_manifest
from core.db import _ALEMBIC_INI, make_engine
from core.vault import Vault
from services.conversations import ConversationStore
from services.research_carryover import seed_carried_research

from ._helpers import client_app

#: The revision immediately before the one under test — where a database that still has a
#: research table sits.
_BEFORE = "76cf84ae88af"

_ASKED = datetime(2026, 3, 1, 9, 30, tzinfo=UTC).replace(tzinfo=None)
_ANSWERED = datetime(2026, 3, 1, 10, 45, tzinfo=UTC).replace(tzinfo=None)


def _migrate(db_path: Path, revision: str) -> None:
    """Run Alembic against ``db_path`` and nothing else."""
    url = f"sqlite:///{db_path}"
    assert os.environ.get("ODYSSEUS_DB_URL") == url, (
        "ODYSSEUS_DB_URL must point at the throwaway copy — alembic.ini defaults to the "
        "operator's live database"
    )
    command.upgrade(Config(str(_ALEMBIC_INI)), revision)


def _downgrade(db_path: Path, revision: str) -> None:
    url = f"sqlite:///{db_path}"
    assert os.environ.get("ODYSSEUS_DB_URL") == url
    command.downgrade(Config(str(_ALEMBIC_INI)), revision)


@pytest.fixture
def db(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "copy.db"
    monkeypatch.setenv("ODYSSEUS_DB_URL", f"sqlite:///{path}")
    return path


async def _vault(tmp_path) -> Vault:
    vault = Vault(tmp_path / "keyfile.json")
    await vault.setup("test-passphrase")
    return vault


def _insert_research(db_path: Path, rows: list[dict]) -> None:
    engine = make_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        for row in rows:
            session.execute(
                text(
                    "INSERT INTO research (id, owner_id, project_id, question_enc, status, "
                    "report_enc, created_at, finished_at) VALUES (:id, :owner_id, "
                    ":project_id, :question_enc, :status, :report_enc, :created_at, "
                    ":finished_at)"
                ),
                row,
            )
        session.commit()
    engine.dispose()


def _table_names(db_path: Path) -> set[str]:
    engine = make_engine(f"sqlite:///{db_path}")
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


async def _seeded_rows(db_path: Path, vault: Vault) -> list[dict]:
    """Every carried thread, read back through the store the operator's own surfaces use —
    which is the assertion that matters: a row whose blob will not decode is a thread that
    cannot be opened."""
    engine = make_engine(f"sqlite:///{db_path}")
    try:
        store = ConversationStore(engine, vault)
        threads = []
        for summary in await store.list_conversations("operator"):
            binding = await store.binding(summary.id)
            turns = await store.messages_view(summary.id)
            threads.append(
                {
                    "id": summary.id,
                    "title": summary.title,
                    "mode": binding.mode,
                    "project_id": binding.project_id,
                    "preview": summary.preview,
                    "turns": [(t.role, t.content) for t in turns],
                }
            )
        return threads
    finally:
        engine.dispose()


class TestTheMigration:
    async def test_every_row_is_copied_out_before_the_table_is_dropped(self, db, tmp_path):
        vault = await _vault(tmp_path)
        _migrate(db, _BEFORE)
        _insert_research(
            db,
            [
                {
                    "id": "r-done",
                    "owner_id": "operator",
                    "project_id": "proj-1",
                    "question_enc": vault.encrypt_str("Why is the sky blue?"),
                    "status": "done",
                    "report_enc": vault.encrypt_str("# Findings\n\nRayleigh scattering."),
                    "created_at": _ASKED,
                    "finished_at": _ANSWERED,
                },
            ],
        )

        _migrate(db, "head")

        tables = _table_names(db)
        assert "research" not in tables
        assert "research_carryover" in tables

    async def test_a_fresh_install_never_grows_the_holding_table(self, db):
        # Nothing to carry, so nothing to carry it in — a new database must not inherit a
        # table whose only purpose is to be drained.
        _migrate(db, "head")
        assert {"research", "research_carryover"} & _table_names(db) == set()

    async def test_downgrade_puts_the_rows_back_rather_than_recreating_an_empty_table(
        self, db, tmp_path
    ):
        vault = await _vault(tmp_path)
        _migrate(db, _BEFORE)
        _insert_research(
            db,
            [
                {
                    "id": "r-1",
                    "owner_id": "operator",
                    "project_id": None,
                    "question_enc": vault.encrypt_str("Which of the two?"),
                    "status": "done",
                    "report_enc": vault.encrypt_str("The first one."),
                    "created_at": _ASKED,
                    "finished_at": _ANSWERED,
                }
            ],
        )
        _migrate(db, "head")
        _downgrade(db, _BEFORE)

        engine = make_engine(f"sqlite:///{db}")
        try:
            with Session(engine) as session:
                row = session.execute(
                    text("SELECT question_enc, report_enc, status FROM research")
                ).one()
        finally:
            engine.dispose()
        assert vault.decrypt_str(row[0]) == "Which of the two?"
        assert vault.decrypt_str(row[1]) == "The first one."
        assert "research_carryover" not in _table_names(db)


class TestTheSeeding:
    async def _carried(self, db, vault) -> None:
        _migrate(db, _BEFORE)
        _insert_research(
            db,
            [
                {
                    "id": "r-done",
                    "owner_id": "operator",
                    "project_id": "proj-1",
                    "question_enc": vault.encrypt_str("Why is the sky blue?"),
                    "status": "done",
                    "report_enc": vault.encrypt_str("# Findings\n\nRayleigh scattering."),
                    "created_at": _ASKED,
                    "finished_at": _ANSWERED,
                },
                {
                    "id": "r-unfinished",
                    "owner_id": "operator",
                    "project_id": None,
                    "question_enc": vault.encrypt_str("What happened to the other one?"),
                    "status": "draft",
                    "report_enc": None,
                    "created_at": _ASKED,
                    "finished_at": None,
                },
            ],
        )
        _migrate(db, "head")

    async def test_a_finished_report_becomes_a_thread_that_opens(self, db, tmp_path):
        vault = await _vault(tmp_path)
        await self._carried(db, vault)

        engine = make_engine(f"sqlite:///{db}")
        try:
            assert await seed_carried_research(engine, vault) == 2
        finally:
            engine.dispose()

        threads = await _seeded_rows(db, vault)
        done = next(t for t in threads if t["title"] == "Why is the sky blue?")
        assert done["mode"] == "research"
        # Filed where the research was filed, so it lands in the scope of the work it
        # belonged to rather than appearing unfiled.
        assert done["project_id"] == "proj-1"
        assert done["turns"] == [
            ("user", "Why is the sky blue?"),
            ("assistant", "# Findings\n\nRayleigh scattering."),
        ]
        # The listing/search projection is written too, so the thread has a preview and is
        # findable rather than being a blank row that only reads once it is opened.
        assert done["preview"] is not None and "Rayleigh" in done["preview"]

    async def test_a_run_that_never_finished_carries_its_question_and_says_so(
        self, db, tmp_path
    ):
        vault = await _vault(tmp_path)
        await self._carried(db, vault)
        engine = make_engine(f"sqlite:///{db}")
        try:
            await seed_carried_research(engine, vault)
        finally:
            engine.dispose()

        threads = await _seeded_rows(db, vault)
        unfinished = next(
            t for t in threads if t["title"] == "What happened to the other one?"
        )
        role, answer = unfinished["turns"][1]
        assert role == "assistant"
        assert "never finished" in answer
        assert "draft" in answer

    async def test_the_thread_is_dated_when_the_research_was(self, db, tmp_path):
        """A carried thread reads as it happened — not as though the operator had asked
        every one of their old questions on the morning of the upgrade."""
        vault = await _vault(tmp_path)
        await self._carried(db, vault)
        engine = make_engine(f"sqlite:///{db}")
        try:
            await seed_carried_research(engine, vault)
            with Session(engine) as session:
                created, updated = session.execute(
                    text(
                        "SELECT created_at, updated_at FROM conversations "
                        "WHERE title_enc IS NOT NULL ORDER BY created_at LIMIT 1"
                    )
                ).one()
        finally:
            engine.dispose()
        assert datetime.fromisoformat(str(created)) == _ASKED
        assert datetime.fromisoformat(str(updated)) in (_ASKED, _ANSWERED)

    async def test_draining_retires_the_holding_table_and_is_idempotent(self, db, tmp_path):
        vault = await _vault(tmp_path)
        await self._carried(db, vault)

        engine = make_engine(f"sqlite:///{db}")
        try:
            assert await seed_carried_research(engine, vault) == 2
            assert "research_carryover" not in set(inspect(engine).get_table_names())
            # A second boot finds no table and does nothing — never a duplicate thread.
            assert await seed_carried_research(engine, vault) == 0
        finally:
            engine.dispose()

        assert len(await _seeded_rows(db, vault)) == 2

    async def test_the_feature_fires_the_carry_over_at_boot(self, monkeypatch):
        """The wiring, which is the half that breaks silently: an unfired one-shot leaves
        the operator's research sitting in a table nothing ever drains."""
        fired: list[tuple] = []

        async def spy(engine, vault) -> int:
            fired.append((engine, vault))
            return 0

        monkeypatch.setattr(research_manifest, "seed_carried_research", spy)
        async with client_app() as (_client, app):
            await asyncio.sleep(0)
            assert fired and fired[0] == (app.state.db_engine, app.state.vault)

    async def test_an_unreadable_row_is_left_behind_rather_than_losing_the_rest(
        self, db, tmp_path
    ):
        """A restored database whose keyfile was replaced. One row that will not decrypt
        must not strand every other report — and must stay in the pen, so a later boot with
        the right key can still carry it."""
        vault = await _vault(tmp_path)
        await self._carried(db, vault)
        engine = make_engine(f"sqlite:///{db}")
        try:
            with Session(engine) as session:
                session.execute(
                    text(
                        "UPDATE research_carryover SET question_enc = 'not-ciphertext' "
                        "WHERE id = 'r-done'"
                    )
                )
                session.commit()
            assert await seed_carried_research(engine, vault) == 1
            with Session(engine) as session:
                left = session.execute(text("SELECT id FROM research_carryover")).all()
        finally:
            engine.dispose()
        assert [row[0] for row in left] == ["r-done"]
