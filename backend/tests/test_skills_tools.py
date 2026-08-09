"""The skills toolset and the per-turn catalog the engine injects (`SKILL-2`, `SKILL-3`)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from pydantic_ai import ModelRetry

from agent.engine import _skill_catalog_block
from core.db import init_db, make_engine
from core.vault import Vault
from services.sandbox import SandboxError
from services.skills import SkillStore
from services.skills.store import SkillCatalogEntry
from tools.deps import RunDeps
from tools.skills import skills_toolset

from .test_skills_bundle import SKILL_MD, _zip

OWNER = "operator"


class FakeSession:
    """A sandbox session that keeps its workspace in a dict — the same `read_file` /
    `write_file` contract the real one exposes, including raising on a missing path."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.writes = 0

    def read_file(self, relpath: str) -> bytes:
        if relpath not in self.files:
            raise SandboxError(f"no such file: {relpath}")
        return self.files[relpath]

    def write_file(self, relpath: str, content: bytes) -> None:
        self.files[relpath] = content
        self.writes += 1


class FakeSessions:
    def __init__(self, session: FakeSession | None = None) -> None:
        self.session = session or FakeSession()

    async def acquire(self, _key: str) -> FakeSession:
        return self.session


class FakeRun:
    id = "run-1"


async def _store() -> SkillStore:
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    vault = Vault(Path(tempfile.mkdtemp()) / "keyfile.json")
    await vault.setup("pw")
    return SkillStore(engine, vault)


def _tool(name: str):
    toolset = skills_toolset()
    return toolset.tools[name].function


def _ctx(deps: RunDeps):
    class Ctx:
        pass

    ctx = Ctx()
    ctx.deps = deps
    return ctx


def _deps(**overrides) -> RunDeps:
    base = {"run": FakeRun(), "owner_id": OWNER, "conversation_id": "conv-1"}
    base.update(overrides)
    return RunDeps(**base)


async def _published(store: SkillStore, **overrides):
    payload = {
        "name": "release-notes",
        "description": "Draft release notes from a changelog.",
        "body": "# Release notes\n\nCollect the merged PRs.",
    }
    payload.update(overrides)
    view = await store.create(OWNER, **payload)
    return await store.set_published(OWNER, view.id, True)


# ── open ─────────────────────────────────────────────────────────────────────────────────


async def test_open_returns_the_instructions_and_stages_the_bundle():
    store = await _store()
    imported, _ = await store.import_bundle(
        OWNER,
        _zip(
            {
                "pdf-processing/SKILL.md": SKILL_MD.encode(),
                "pdf-processing/scripts/fill.py": b"print('filling')\n",
            }
        ),
        "pdf-processing.zip",
    )
    await store.set_published(OWNER, imported.id, True)
    sessions = FakeSessions()

    result = await _tool("open")(
        _ctx(_deps(skills=store, sandbox_sessions=sessions)), "pdf-processing"
    )

    assert result["ok"] is True
    assert "PDF processing" in result["instructions"]
    assert result["allowed_tools"] == ["Read", "Bash"]
    assert result["files"] == [
        "/work/skills/pdf-processing/SKILL.md",
        "/work/skills/pdf-processing/scripts/fill.py",
    ]
    assert sessions.session.files["skills/pdf-processing/scripts/fill.py"] == b"print('filling')\n"
    # The staged SKILL.md is the rendered standard artifact, not just the body.
    assert sessions.session.files["skills/pdf-processing/SKILL.md"].startswith(b"---\n")


async def test_reopening_a_skill_does_not_rewrite_identical_files():
    store = await _store()
    await _published(store)
    sessions = FakeSessions()
    deps = _deps(skills=store, sandbox_sessions=sessions)

    await _tool("open")(_ctx(deps), "release-notes")
    after_first = sessions.session.writes
    await _tool("open")(_ctx(deps), "release-notes")

    assert sessions.session.writes == after_first


async def test_open_refuses_a_draft_the_same_way_as_an_unknown_name():
    """A draft must be indistinguishable from nonexistent — the operator hasn't
    published it, so the agent should not learn it exists."""
    store = await _store()
    await store.create(OWNER, name="secret-draft", description="Not ready.", body="x")
    await _published(store)

    with pytest.raises(ModelRetry) as caught:
        await _tool("open")(_ctx(_deps(skills=store)), "secret-draft")
    assert "secret-draft" not in str(caught.value).split("Available skills:")[1]
    assert "release-notes" in str(caught.value)


async def test_open_without_a_sandbox_still_returns_instructions():
    store = await _store()
    await _published(store)
    result = await _tool("open")(_ctx(_deps(skills=store)), "release-notes")
    assert result["ok"] is True
    assert result["files"] == []
    assert "unavailable" in result["note"]


async def test_open_survives_a_sandbox_failure():
    class FailingSessions:
        async def acquire(self, _key):
            raise SandboxError("no runtime")

    store = await _store()
    await _published(store)
    result = await _tool("open")(
        _ctx(_deps(skills=store, sandbox_sessions=FailingSessions())), "release-notes"
    )
    assert result["ok"] is True
    assert "could not be staged" in result["note"]


async def test_tools_degrade_when_the_capability_is_absent():
    for name, args in [
        ("open", ("anything",)),
        ("create", ("a-skill", "desc", "body")),
        ("edit", ("a-skill", "old", "new")),
    ]:
        result = await _tool(name)(_ctx(_deps()), *args)
        assert result["ok"] is False
        assert "unavailable" in result["error"]


# ── create / edit ────────────────────────────────────────────────────────────────────────


async def test_create_only_ever_writes_a_draft():
    store = await _store()
    result = await _tool("create")(
        _ctx(_deps(skills=store)), "deploy-checks", "Check a deploy is safe.", "1. Look."
    )
    assert result["ok"] is True
    assert result["status"] == "draft"

    saved = await store.get_by_name(OWNER, "deploy-checks")
    assert saved.published is False
    assert saved.source == "agent"
    assert await store.catalog(OWNER) == []


async def test_create_asks_the_model_to_retry_on_an_invalid_name():
    store = await _store()
    with pytest.raises(ModelRetry, match="name"):
        await _tool("create")(_ctx(_deps(skills=store)), "Not A Slug", "desc", "body")


async def test_edit_replaces_one_span():
    store = await _store()
    await _published(store)
    result = await _tool("edit")(
        _ctx(_deps(skills=store)), "release-notes", "Collect the merged PRs.", "Collect the tags."
    )
    assert result["ok"] is True
    assert "Collect the tags." in (await store.get_by_name(OWNER, "release-notes")).body


@pytest.mark.parametrize(
    ("body", "old", "expected"),
    [
        ("one two", "missing", "was not found"),
        ("dup dup", "dup", "matched 2 places"),
    ],
)
async def test_edit_retries_with_a_precise_reason(body, old, expected):
    store = await _store()
    await _published(store, body=body)
    with pytest.raises(ModelRetry, match=expected):
        await _tool("edit")(_ctx(_deps(skills=store)), "release-notes", old, "x")


# ── the injected catalog ─────────────────────────────────────────────────────────────────


def test_catalog_block_is_empty_with_no_published_skills():
    assert _skill_catalog_block([]) == ""


def test_catalog_block_lists_each_skill():
    block = _skill_catalog_block(
        [
            SkillCatalogEntry(name="release-notes", description="Draft release notes."),
            SkillCatalogEntry(name="triage-bugs", description="Triage a bug report."),
        ]
    )
    assert "- release-notes: Draft release notes." in block
    assert "- triage-bugs: Triage a bug report." in block
    assert "skills_open" in block


def test_catalog_block_reports_what_the_budget_dropped():
    entries = [
        SkillCatalogEntry(name=f"skill-{i}", description="d" * 200) for i in range(100)
    ]
    block = _skill_catalog_block(entries)
    assert "…and" in block and "more" in block
    # Newest-first ordering means the first entries survive and the tail is what's dropped.
    assert "skill-0" in block
    assert "skill-99" not in block


async def test_catalog_reaches_the_block_with_published_skills_only():
    store = await _store()
    await store.create(OWNER, name="a-draft", description="Draft.", body="x")
    await _published(store)
    block = _skill_catalog_block(await store.catalog(OWNER))
    assert "release-notes" in block
    assert "a-draft" not in block


# ── Regressions ──────────────────────────────────────────────────────────────────────────


async def test_edit_refuses_a_draft_the_same_way_open_does():
    """A draft is the operator's unreviewed work: the agent must neither rewrite one nor
    learn it exists from a differing error."""
    store = await _store()
    draft = await store.create(
        OWNER, name="secret-draft", description="Not ready.", body="do the private thing"
    )
    await _published(store)

    with pytest.raises(ModelRetry) as caught:
        await _tool("edit")(
            _ctx(_deps(skills=store)), "secret-draft", "private", "public"
        )
    message = str(caught.value)
    assert "No published skill named" in message
    assert "secret-draft" not in message.split("Available skills:")[1]
    # …and the draft is untouched.
    assert (await store.get(OWNER, draft.id)).body == "do the private thing"
