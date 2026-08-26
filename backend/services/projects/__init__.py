"""Projects — the operator's working directories, and the scope the app filters by."""

from __future__ import annotations

from services.projects.store import (
    ProjectStore,
    ProjectView,
    RepoProbe,
    project_clause,
    visible_project_ids,
)
from services.projects.worktree import (
    Diff,
    WorktreeBusyError,
    WorktreeError,
    WorktreeManager,
    WorktreeState,
    branch_for,
)

__all__ = [
    "Diff",
    "ProjectStore",
    "ProjectView",
    "RepoProbe",
    "WorktreeBusyError",
    "WorktreeError",
    "WorktreeManager",
    "WorktreeState",
    "branch_for",
    "project_clause",
    "visible_project_ids",
]
