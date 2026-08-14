"""`BACKUP-2`: importing merges — no duplicates, every record stamped with the operator."""

from __future__ import annotations

import pytest
from sqlmodel import Session, select

from core.db import init_db, make_engine
from core.exceptions import DegradedCapabilityError
from core.vault import Vault
from models.memory import Memory
from models.skill import Skill, SkillFile
from services.backup import BackupFormatError, BackupSecretError, BackupService
from services.memory import MemoryStore
from services.settings_store import SettingsStore
from services.skills import SkillStore

OWNER = "operator"
OTHER_OWNER = "someone-else"
BACKUP_SECRET = "correct horse battery staple"


class _NoEmbedder:
    async def is_available(self, owner_id: str) -> bool:
        return False

    async def embed(self, owner_id: str, texts: list[str]):
        raise DegradedCapabilityError("no embedding endpoint configured")


async def _host(tmp_path, name: str):
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    vault = Vault(tmp_path / f"{name}-keyfile.json")
    await vault.setup(f"{name}-password")
    return engine, vault, BackupService(engine, vault, SettingsStore(engine))


def _memories(engine, vault) -> MemoryStore:
    return MemoryStore(engine, vault, _NoEmbedder())


def _count(engine, model, owner_id: str = OWNER) -> int:
    with Session(engine) as session:
        return len(list(session.exec(select(model).where(model.owner_id == owner_id)).all()))


async def test_reimporting_the_same_file_twice_changes_nothing(tmp_path):
    source_engine, source_vault, source = await _host(tmp_path, "source")
    store = _memories(source_engine, source_vault)
    await store.remember(OWNER, "Deploys go out on Thursdays")
    await store.remember(OWNER, "The wifi password is on the fridge")
    envelope, _ = await source.export(OWNER, BACKUP_SECRET)

    target_engine, target_vault, target = await _host(tmp_path, "target")
    first = await target.import_backup(OWNER, BACKUP_SECRET, envelope)
    assert first.imported["memories"] == 2
    assert first.skipped["memories"] == 0

    second = await target.import_backup(OWNER, BACKUP_SECRET, envelope)
    assert second.imported["memories"] == 0
    assert second.skipped["memories"] == 2
    assert _count(target_engine, Memory) == 2


async def test_a_record_that_exists_by_natural_key_is_not_duplicated(tmp_path):
    source_engine, source_vault, source = await _host(tmp_path, "source")
    await _memories(source_engine, source_vault).remember(OWNER, "Deploys go out on Thursdays")
    envelope, _ = await source.export(OWNER, BACKUP_SECRET)

    # The target already knows this fact — same content, its own row, its own id.
    target_engine, target_vault, target = await _host(tmp_path, "target")
    await _memories(target_engine, target_vault).remember(OWNER, "Deploys go out on Thursdays")

    report = await target.import_backup(OWNER, BACKUP_SECRET, envelope)
    assert report.imported["memories"] == 0
    assert report.skipped["memories"] == 1
    assert _count(target_engine, Memory) == 1


async def test_imported_records_are_attributed_to_the_importing_operator(tmp_path):
    source_engine, source_vault, source = await _host(tmp_path, "source")
    # Exported by one owner…
    await _memories(source_engine, source_vault).remember(OTHER_OWNER, "A fact")
    envelope, _ = await source.export(OTHER_OWNER, BACKUP_SECRET)

    # …imported by another: the ownership seam is re-stamped, not carried over.
    target_engine, target_vault, target = await _host(tmp_path, "target")
    report = await target.import_backup(OWNER, BACKUP_SECRET, envelope)

    assert report.imported["memories"] == 1
    assert _count(target_engine, Memory, OWNER) == 1
    assert _count(target_engine, Memory, OTHER_OWNER) == 0


async def test_a_skill_and_its_files_survive_the_round_trip(tmp_path):
    source_engine, source_vault, source = await _host(tmp_path, "source")
    skills = SkillStore(source_engine, source_vault)
    skill = await skills.create(
        OWNER, name="deploy-runbook", description="How we ship", body="1. Push."
    )
    await skills.put_file(OWNER, skill.id, "scripts/ship.sh", b"#!/bin/sh\necho shipping\n")
    envelope, _ = await source.export(OWNER, BACKUP_SECRET, include=["skills"])

    target_engine, target_vault, target = await _host(tmp_path, "target")
    report = await target.import_backup(OWNER, BACKUP_SECRET, envelope)
    assert report.imported["skills"] == 2  # the skill plus its one file

    restored = await SkillStore(target_engine, target_vault).list_skills(OWNER)
    assert [s.name for s in restored] == ["deploy-runbook"]
    # Ids are preserved, so the file is still attached to its skill — no remapping pass.
    assert _count(target_engine, SkillFile) == 1
    body = await SkillStore(target_engine, target_vault).file_content(
        OWNER, restored[0].id, "scripts/ship.sh"
    )
    assert body == b"#!/bin/sh\necho shipping\n"

    # And a second import of the same bundle adds nothing.
    again = await target.import_backup(OWNER, BACKUP_SECRET, envelope)
    assert again.imported["skills"] == 0
    assert _count(target_engine, Skill) == 1


async def test_include_limits_what_a_restore_touches(tmp_path):
    source_engine, source_vault, source = await _host(tmp_path, "source")
    await _memories(source_engine, source_vault).remember(OWNER, "A fact")
    await SkillStore(source_engine, source_vault).create(
        OWNER, name="a-skill", description="d", body="b"
    )
    envelope, _ = await source.export(OWNER, BACKUP_SECRET)

    target_engine, _, target = await _host(tmp_path, "target")
    report = await target.import_backup(OWNER, BACKUP_SECRET, envelope, include=["memories"])
    assert report.imported["memories"] == 1
    assert "skills" not in report.imported
    assert _count(target_engine, Skill) == 0


async def test_a_wrong_secret_or_a_foreign_file_is_refused(tmp_path):
    source_engine, source_vault, source = await _host(tmp_path, "source")
    await _memories(source_engine, source_vault).remember(OWNER, "A fact")
    envelope, _ = await source.export(OWNER, BACKUP_SECRET)

    _, _, target = await _host(tmp_path, "target")
    with pytest.raises(BackupSecretError):
        await target.import_backup(OWNER, "wrong-secret", envelope)
    with pytest.raises(BackupFormatError):
        await target.import_backup(OWNER, BACKUP_SECRET, {"format": "something-else"})
