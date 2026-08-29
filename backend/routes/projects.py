"""The projects surface — the operator's working directories and the active selection.

Thin over `services/projects`. Two shapes deserve a note:

`repo` on every listing is **probed live**, not stored. Whether a directory is a git
repository, and how many changes are uncommitted, are facts about the world that change
without us; caching them would mean showing the operator a stale answer to the one
question that decides whether coding mode is safe to start.

`uncommittedChanges` is surfaced deliberately, and the UI is expected to show it. Coding
mode branches a worktree from the project's base ref, so uncommitted work in the
operator's own tree is **invisible to the agent**. That is the price of never touching
their tree, and it should be read on the project screen rather than discovered halfway
through a session.

camelCase out, matching the `corpus`/`uploads`/`tasks` surfaces the frontend
seams were built against.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from core.exceptions import InvalidInputError, NotFoundError
from routes import deps
from routes.camel import CamelModel
from routes.deps import OPERATOR_ID
from services.projects import ProjectView, WorktreeError

router = APIRouter(prefix="/projects", tags=["projects"])


class RepoOut(CamelModel):
    exists: bool
    is_git_repo: bool
    uncommitted_changes: int | None = None
    current_branch: str | None = None


class ProjectOut(CamelModel):
    id: str
    name: str
    root_path: str
    git_initialized: bool
    base_ref: str
    archived: bool
    created_at: datetime
    last_opened_at: datetime
    repo: RepoOut


class ProjectCreate(CamelModel):
    name: str = ""
    root_path: str


class ProjectUpdate(CamelModel):
    name: str | None = None
    base_ref: str | None = None
    archived: bool | None = None


class ProjectsOut(CamelModel):
    projects: list[ProjectOut]
    #: The operator's current selection, or null when nothing is active — which means
    #: they see exactly the unfiled rows they saw before projects existed.
    active_id: str | None = None


def _out(view: ProjectView) -> ProjectOut:
    return ProjectOut(
        id=view.id,
        name=view.name,
        root_path=view.root_path,
        git_initialized=view.git_initialized,
        base_ref=view.base_ref,
        archived=view.archived,
        created_at=view.created_at,
        last_opened_at=view.last_opened_at,
        repo=RepoOut(
            exists=view.probe.exists,
            is_git_repo=view.probe.is_git_repo,
            uncommitted_changes=view.probe.uncommitted_changes,
            current_branch=view.probe.current_branch,
        ),
    )


@router.get("", response_model=ProjectsOut)
async def list_projects(request: Request, include_archived: bool = False) -> ProjectsOut:
    store = deps.projects(request)
    views = await store.list(OPERATOR_ID, include_archived=include_archived)
    return ProjectsOut(
        projects=[_out(v) for v in views],
        active_id=await store.active_id(OPERATOR_ID),
    )


@router.post("", response_model=ProjectOut, status_code=201)
async def create_project(request: Request, body: ProjectCreate) -> ProjectOut:
    try:
        return _out(await deps.projects(request).create(OPERATOR_ID, body.name, body.root_path))
    except InvalidInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(request: Request, project_id: str) -> ProjectOut:
    try:
        return _out(await deps.projects(request).get(OPERATOR_ID, project_id))
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(request: Request, project_id: str, body: ProjectUpdate) -> ProjectOut:
    try:
        return _out(
            await deps.projects(request).update(
                OPERATOR_ID,
                project_id,
                name=body.name,
                base_ref=body.base_ref,
                archived=body.archived,
            )
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{project_id}", status_code=204)
async def delete_project(request: Request, project_id: str) -> None:
    try:
        await deps.projects(request).delete(OPERATOR_ID, project_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{project_id}/init-repo", response_model=ProjectOut)
async def init_repo(request: Request, project_id: str) -> ProjectOut:
    """Make the project's directory a git repository, with the operator's explicit yes.

    Coding mode needs one — a worktree is cut from it — but running `git init` and
    committing someone's whole directory is a real, visible side effect, so it is never
    implicit. This route *is* the confirmation: the UI asks, the operator answers, and
    only then does anything happen. The agent has no path to it.
    """
    store = deps.projects(request)
    try:
        project = await store.get(OPERATOR_ID, project_id)
        created = await deps.worktrees(request).ensure_repo(
            Path(project.root_path), confirmed=True
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (InvalidInputError, WorktreeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if created:
        await store.update(OPERATOR_ID, project_id, git_initialized=True)
    return _out(await store.get(OPERATOR_ID, project_id))


@router.post("/{project_id}/activate", response_model=ProjectsOut)
async def activate_project(request: Request, project_id: str) -> ProjectsOut:
    """Make this the operator's active project. Returns the whole listing, because the
    selection changes what every other surface will return and the client should reseat
    from one shape rather than patching a local guess."""
    store = deps.projects(request)
    try:
        await store.activate(OPERATOR_ID, project_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return await list_projects(request)


@router.post("/deactivate", response_model=ProjectsOut)
async def deactivate_project(request: Request) -> ProjectsOut:
    """Clear the selection — the ALL PROJECTS state, which is the app's original
    behavior and not an empty one."""
    await deps.projects(request).activate(OPERATOR_ID, None)
    return await list_projects(request)
