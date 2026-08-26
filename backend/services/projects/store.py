"""The project catalog: CRUD, the active selection, and the git probe.

Three things here are worth knowing before changing anything.

**Null means unfiled, and unfiled is visible everywhere.** `visible_project_ids` is the
one place the scope rule lives, and every filtered query in the app reads it rather than
writing its own `WHERE`. The rule is:

    visible   = unfiled  ∪  the active project
    invisible = every other project

That is what makes the scope safe to introduce over an existing database — every row
that already exists is unfiled, so activating a project *adds* to what the operator sees
and never subtracts. It is also why lists and recall use the same helper: a project chat
that could not reach the operator's general memory would be a worse assistant, and a
chat that could reach *another* project's notes would be a leak.

**The path is sealed; the git facts are not.** A directory path names the operator's
clients and employers, so `root_path_enc` is vault-sealed like any other content. Whether
the directory is a repo, and how many changes are uncommitted, are facts about the
world that we re-probe on every read anyway.

**`probe` never mutates.** It answers "what is this directory" so the UI can ask the
operator whether to `git init` — running one is a separate, explicitly confirmed act
(`services/projects/worktree.py`). A read that quietly created a repository in someone's
directory would be exactly the kind of surprise this feature exists to avoid.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import Engine, or_
from sqlmodel import Session, select

from core.db import in_session
from core.exceptions import InvalidInputError, NotFoundError
from core.vault import Vault
from models._fields import utcnow
from models.project import Project
from services.settings_store import ACTIVE_PROJECT_KEY, SettingsStore


def visible_project_ids(active: str | None) -> tuple[str | None, ...]:
    """The project ids a query may return rows for: unfiled, plus the active project."""
    return (None,) if active is None else (None, active)


def project_clause(column, visible: tuple[str | None, ...] | None):
    """The scope rule as one SQL clause, or ``None`` for no filtering at all.

    Every scoped query goes through this rather than writing its own ``WHERE``, because
    the rule has a trap in it: SQL ``IN`` never matches NULL, so the obvious
    ``column.in_(visible)`` silently drops every **unfiled** row — which is every row
    that existed before projects did. A query written that way looks correct, passes a
    test that only uses filed rows, and blanks the operator's history in production.

    ``visible=None`` means the caller asked for everything (the ALL PROJECTS scope) and
    gets no clause at all.
    """
    if visible is None:
        return None
    filed = [pid for pid in visible if pid is not None]
    unfiled = column.is_(None)
    return unfiled if not filed else or_(unfiled, column.in_(filed))


@dataclass(frozen=True)
class RepoProbe:
    """What a directory actually is, right now. Re-read on every listing."""

    exists: bool
    is_git_repo: bool
    # None when the path is not a repo — distinct from 0, which means a clean tree.
    uncommitted_changes: int | None = None
    current_branch: str | None = None


@dataclass(frozen=True)
class ProjectView:
    id: str
    name: str
    root_path: str
    git_initialized: bool
    base_ref: str
    archived: bool
    created_at: datetime
    last_opened_at: datetime
    probe: RepoProbe


async def _run_git(cwd: Path, *args: str) -> tuple[int, str]:
    """One `git` invocation with a fixed argv and no shell. Returns (code, stdout)."""
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    return proc.returncode or 0, out.decode("utf-8", "replace")


async def probe_repo(root: Path) -> RepoProbe:
    if not root.is_dir():
        return RepoProbe(exists=False, is_git_repo=False)
    code, _ = await _run_git(root, "rev-parse", "--is-inside-work-tree")
    if code != 0:
        return RepoProbe(exists=True, is_git_repo=False)
    _, status = await _run_git(root, "status", "--porcelain")
    _, branch = await _run_git(root, "rev-parse", "--abbrev-ref", "HEAD")
    changed = len([line for line in status.splitlines() if line.strip()])
    return RepoProbe(
        exists=True,
        is_git_repo=True,
        uncommitted_changes=changed,
        current_branch=branch.strip() or None,
    )


class ProjectStore:
    """Owner-scoped project catalog. Vault-sealed paths; the active selection is a
    preference, not session state, so it survives a reload and a lock."""

    def __init__(self, db_engine: Engine, vault: Vault, settings: SettingsStore) -> None:
        self._db = db_engine
        self._vault = vault
        self._settings = settings

    async def _view(self, row: Project) -> ProjectView:
        root = Path(self._vault.decrypt_str(row.root_path_enc))
        return ProjectView(
            id=row.id,
            name=row.name,
            root_path=str(root),
            git_initialized=row.git_initialized,
            base_ref=row.base_ref,
            archived=row.archived,
            created_at=row.created_at,
            last_opened_at=row.last_opened_at,
            probe=await probe_repo(root),
        )

    async def list(self, owner_id: str, *, include_archived: bool = False) -> list[ProjectView]:
        def work(session: Session) -> list[Project]:
            query = select(Project).where(Project.owner_id == owner_id)
            if not include_archived:
                query = query.where(Project.archived == False)  # noqa: E712 — SQL boolean compare
            return list(session.exec(query.order_by(Project.last_opened_at.desc())).all())

        rows = await in_session(self._db, work)
        # Probes shell out, so fan them out rather than paying serially per project.
        return list(await asyncio.gather(*(self._view(row) for row in rows)))

    async def get(self, owner_id: str, project_id: str) -> ProjectView:
        return await self._view(await self._row(owner_id, project_id))

    async def _row(self, owner_id: str, project_id: str) -> Project:
        def work(session: Session) -> Project | None:
            row = session.get(Project, project_id)
            return row if row is not None and row.owner_id == owner_id else None

        row = await in_session(self._db, work)
        if row is None:
            raise NotFoundError("project not found")
        return row

    async def create(self, owner_id: str, name: str, root_path: str) -> ProjectView:
        root = Path(root_path).expanduser()
        if not root.is_absolute():
            # A browser cannot produce an absolute host path, so the operator either
            # typed one or used the native picker. A relative path here would resolve
            # against the *server's* cwd, which is never what they meant.
            raise InvalidInputError("project path must be absolute")
        if not root.is_dir():
            raise InvalidInputError(f"no such directory: {root}")
        resolved = root.resolve()
        sealed = self._vault.encrypt_str(str(resolved))

        def work(session: Session) -> Project:
            row = Project(
                owner_id=owner_id,
                name=name.strip() or resolved.name,
                root_path_enc=sealed,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return row

        return await self._view(await in_session(self._db, work))

    async def update(
        self,
        owner_id: str,
        project_id: str,
        *,
        name: str | None = None,
        base_ref: str | None = None,
        archived: bool | None = None,
        git_initialized: bool | None = None,
    ) -> ProjectView:
        row = await self._row(owner_id, project_id)

        def work(session: Session) -> Project:
            stored = session.get(Project, row.id)
            assert stored is not None  # _row already proved ownership in this process
            if name is not None:
                stored.name = name
            if base_ref is not None:
                stored.base_ref = base_ref
            if archived is not None:
                stored.archived = archived
            if git_initialized is not None:
                stored.git_initialized = git_initialized
            session.add(stored)
            session.commit()
            session.refresh(stored)
            return stored

        return await self._view(await in_session(self._db, work))

    async def delete(self, owner_id: str, project_id: str) -> None:
        row = await self._row(owner_id, project_id)

        def work(session: Session) -> None:
            stored = session.get(Project, row.id)
            if stored is not None:
                session.delete(stored)
                session.commit()

        await in_session(self._db, work)
        # Deleting the active project leaves nothing active rather than a dangling id.
        if await self.active_id(owner_id) == project_id:
            await self.activate(owner_id, None)

    async def active_id(self, owner_id: str) -> str | None:
        value = await self._settings.get(owner_id, ACTIVE_PROJECT_KEY)
        return value or None

    async def activate(self, owner_id: str, project_id: str | None) -> None:
        if project_id is not None:
            await self._row(owner_id, project_id)  # 404 rather than a dangling selection

            def touch(session: Session) -> None:
                stored = session.get(Project, project_id)
                if stored is not None:
                    stored.last_opened_at = utcnow()
                    session.add(stored)
                    session.commit()

            await in_session(self._db, touch)
        await self._settings.set(owner_id, ACTIVE_PROJECT_KEY, project_id or "")

    async def root_path(self, owner_id: str, project_id: str) -> Path:
        """The decrypted host root. The one accessor the worktree layer needs, kept here
        so nothing else has to know the column is sealed."""
        row = await self._row(owner_id, project_id)
        return Path(self._vault.decrypt_str(row.root_path_enc))
