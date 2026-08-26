"""The coding branch surface — review what a coding conversation changed, then land it.

A coding thread works on `ody/<conversation-id>` in a worktree beside the project, never
in the operator's own checkout. These three endpoints are how that work gets back:

- ``GET /worktrees/{conversation_id}`` — the diffstat and the patch, against the project's
  base ref.
- ``POST .../merge`` — **the one operation that writes the operator's tree**. It is not
  approval-gated in the agent sense because it cannot be: the agent never calls it. The
  operator pressing MERGE *is* the approval, which is why this is a route and not a tool.
- ``POST .../discard`` — throw the branch away.

Keyed by conversation rather than by branch name, because that is what the operator is
looking at when they decide. camelCase out, matching the projects surface beside it.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from core.exceptions import NotFoundError
from routes import deps
from routes.camel import CamelModel
from routes.deps import OPERATOR_ID
from services.conversations import ConversationBinding
from services.projects import WorktreeError, branch_for

router = APIRouter(prefix="/worktrees", tags=["projects"])


class BranchOut(CamelModel):
    conversation_id: str
    project_id: str
    branch: str
    base_ref: str
    files_changed: int
    insertions: int
    deletions: int
    patch: str
    #: Whether this conversation currently holds the project's single checkout. False
    #: means another coding thread has it — the branch still exists and is still
    #: mergeable, it just isn't the one checked out right now.
    active: bool


class MergedOut(CamelModel):
    merged: bool
    detail: str


async def _resolve(request: Request, conversation_id: str) -> tuple[ConversationBinding, Path]:
    """The thread's project and its root path, or a 4xx explaining which half is missing."""
    binding = await deps.store(request).binding(conversation_id)
    if binding.mode != "coding" or not binding.project_id:
        raise HTTPException(status_code=404, detail="not a coding conversation")
    try:
        project = await deps.projects(request).get(OPERATOR_ID, binding.project_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return binding, Path(project.root_path)


@router.get("/{conversation_id}", response_model=BranchOut)
async def read_branch(request: Request, conversation_id: str) -> BranchOut:
    binding, root = await _resolve(request, conversation_id)
    project = await deps.projects(request).get(OPERATOR_ID, binding.project_id or "")
    worktrees = deps.worktrees(request)
    try:
        diff = await worktrees.diff(
            root, base_ref=project.base_ref, conversation_id=conversation_id
        )
    except WorktreeError:
        # No branch yet — a coding thread that hasn't touched a file. An empty diff is
        # the honest answer, not an error the UI has to special-case.
        diff = None
    return BranchOut(
        conversation_id=conversation_id,
        project_id=project.id,
        branch=branch_for(conversation_id),
        base_ref=project.base_ref,
        files_changed=diff.files_changed if diff else 0,
        insertions=diff.insertions if diff else 0,
        deletions=diff.deletions if diff else 0,
        patch=diff.patch if diff else "",
        active=worktrees.holder(project.id) == conversation_id,
    )


@router.post("/{conversation_id}/merge", response_model=MergedOut)
async def merge_branch(request: Request, conversation_id: str) -> MergedOut:
    binding, root = await _resolve(request, conversation_id)
    project = await deps.projects(request).get(OPERATOR_ID, binding.project_id or "")
    try:
        detail = await deps.worktrees(request).merge(
            root, base_ref=project.base_ref, conversation_id=conversation_id
        )
    except WorktreeError as exc:
        # A conflict is git's own message and the operator's to resolve — handing it
        # back verbatim beats paraphrasing it into something less actionable.
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return MergedOut(merged=True, detail=detail.strip())


@router.post("/{conversation_id}/discard", status_code=204)
async def discard_branch(request: Request, conversation_id: str) -> None:
    binding, root = await _resolve(request, conversation_id)
    await deps.worktrees(request).discard(
        root, project_id=binding.project_id or "", conversation_id=conversation_id
    )
