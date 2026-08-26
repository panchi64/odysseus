"""Projects: the catalog, the active selection, and the one scope rule.

The scope rule is the reason this feature is safe to introduce over an existing
database, so it is what these tests are mostly about:

    visible   = unfiled  ∪  the active project
    invisible = every other project

The load-bearing assertion is that a row created *before* projects existed
(``project_id is None``) stays visible once a project is activated. Get that wrong and
activating the first project blanks the operator's entire history — which is exactly the
kind of failure that looks like a working feature in every other test.
"""

from __future__ import annotations

import pytest
from sqlmodel import Session, select

from core.db import init_db, make_engine
from core.exceptions import InvalidInputError, NotFoundError
from core.vault import Vault
from models.conversation import Conversation
from services.projects import ProjectStore, project_clause, visible_project_ids
from services.settings_store import SettingsStore
from tests._helpers import client_app


async def _store(tmp_path) -> ProjectStore:
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    vault = Vault(tmp_path / "keyfile.json")
    await vault.setup("pw")
    return ProjectStore(engine, vault, SettingsStore(engine))


class TestScopeRule:
    def test_unfiled_is_visible_with_no_active_project(self):
        assert visible_project_ids(None) == (None,)

    def test_active_project_adds_to_unfiled_never_replaces_it(self):
        # The whole safety argument: None (unfiled) survives activation.
        assert visible_project_ids("proj-a") == (None, "proj-a")

    def test_another_project_is_never_visible(self):
        assert "proj-b" not in visible_project_ids("proj-a")


class TestCatalog:
    async def test_create_seals_the_path_and_probes_the_repo(self, tmp_path):
        store = await _store(tmp_path)
        work = tmp_path / "work"
        work.mkdir()

        view = await store.create("operator", "Work", str(work))

        assert view.root_path == str(work.resolve())
        assert view.probe.exists is True
        # A plain directory is not a repo, and `uncommitted_changes` stays None rather
        # than 0 — "not a repo" and "a clean repo" are different answers.
        assert view.probe.is_git_repo is False
        assert view.probe.uncommitted_changes is None

    async def test_name_defaults_to_the_directory_name(self, tmp_path):
        store = await _store(tmp_path)
        work = tmp_path / "odysseus"
        work.mkdir()
        view = await store.create("operator", "  ", str(work))
        assert view.name == "odysseus"

    async def test_relative_path_is_refused(self, tmp_path):
        store = await _store(tmp_path)
        # A relative path would resolve against the *server's* cwd, never what the
        # operator meant, so it is rejected rather than silently reinterpreted.
        with pytest.raises(InvalidInputError):
            await store.create("operator", "x", "relative/dir")

    async def test_missing_directory_is_refused(self, tmp_path):
        store = await _store(tmp_path)
        with pytest.raises(InvalidInputError):
            await store.create("operator", "x", str(tmp_path / "nope"))

    async def test_another_owners_project_is_not_found(self, tmp_path):
        store = await _store(tmp_path)
        work = tmp_path / "work"
        work.mkdir()
        view = await store.create("operator", "Work", str(work))
        with pytest.raises(NotFoundError):
            await store.get("someone-else", view.id)


class TestActiveSelection:
    async def test_nothing_is_active_by_default(self, tmp_path):
        store = await _store(tmp_path)
        assert await store.active_id("operator") is None

    async def test_activate_then_deactivate_round_trips(self, tmp_path):
        store = await _store(tmp_path)
        work = tmp_path / "work"
        work.mkdir()
        view = await store.create("operator", "Work", str(work))

        await store.activate("operator", view.id)
        assert await store.active_id("operator") == view.id

        await store.activate("operator", None)
        assert await store.active_id("operator") is None

    async def test_activating_an_unknown_project_is_refused(self, tmp_path):
        store = await _store(tmp_path)
        # Refused rather than stored, so the selection can never dangle.
        with pytest.raises(NotFoundError):
            await store.activate("operator", "no-such-project")
        assert await store.active_id("operator") is None

    async def test_deleting_the_active_project_clears_the_selection(self, tmp_path):
        store = await _store(tmp_path)
        work = tmp_path / "work"
        work.mkdir()
        view = await store.create("operator", "Work", str(work))
        await store.activate("operator", view.id)

        await store.delete("operator", view.id)

        assert await store.active_id("operator") is None


class TestProjectClause:
    """The SQL half of the rule, over real rows.

    ``project_clause`` exists because ``column.in_(visible)`` reads as correct and is
    not: SQL ``IN`` never matches NULL, so it silently drops every unfiled row. These
    assert the behavior that mistake would break.
    """

    @staticmethod
    def _seeded():
        engine = make_engine("sqlite:///:memory:")
        init_db(engine)
        with Session(engine) as session:
            session.add(Conversation(owner_id="operator", project_id=None))  # pre-project
            session.add(Conversation(owner_id="operator", project_id="proj-a"))
            session.add(Conversation(owner_id="operator", project_id="proj-b"))
            session.commit()
        return engine

    @staticmethod
    def _ids(engine, visible) -> list[str]:
        with Session(engine) as session:
            query = select(Conversation)
            clause = project_clause(Conversation.project_id, visible)
            if clause is not None:
                query = query.where(clause)
            return sorted(str(c.project_id) for c in session.exec(query).all())

    def test_unfiled_rows_survive_activating_a_project(self):
        # THE assertion. A pre-projects conversation must not vanish the moment the
        # operator opens their first project.
        assert self._ids(self._seeded(), visible_project_ids("proj-a")) == ["None", "proj-a"]

    def test_another_project_is_excluded(self):
        assert "proj-b" not in self._ids(self._seeded(), visible_project_ids("proj-a"))

    def test_no_active_project_shows_only_unfiled(self):
        assert self._ids(self._seeded(), visible_project_ids(None)) == ["None"]

    def test_none_means_no_filter_at_all(self):
        # The ALL PROJECTS scope — every row, filed or not.
        assert self._ids(self._seeded(), None) == ["None", "proj-a", "proj-b"]


class TestRoutes:
    async def test_feature_wires_up_and_round_trips(self, tmp_path):
        async with client_app() as (client, app):
            assert hasattr(app.state, "projects")

            work = tmp_path / "proj"
            work.mkdir()
            created = await client.post("/projects", json={"name": "P", "rootPath": str(work)})
            assert created.status_code == 201, created.text
            pid = created.json()["id"]

            listing = (await client.get("/projects")).json()
            assert [p["id"] for p in listing["projects"]] == [pid]
            assert listing["activeId"] is None

            activated = (await client.post(f"/projects/{pid}/activate")).json()
            assert activated["activeId"] == pid

            assert (await client.post("/projects/deactivate")).json()["activeId"] is None

    async def test_the_project_toolset_is_in_the_catalog(self):
        async with client_app() as (_client, app):
            # Registered as an ordinary category, so it appears in the operator's
            # tool settings and can be toggled like every other tool.
            assert "project" in app.state.tool_categories
