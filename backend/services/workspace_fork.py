"""Forking a workspace for a delegated agent, and reporting what came back.

A sub-agent that *changes* things never works in the workspace that delegated to it. It
gets its own copy — a sandbox session cloned from the parent's, or its own checkout on its
own branch — and what it changed is merged back afterwards, with any conflict *reported*
rather than resolved in its favour. That is the whole of what this module owns: taking the
copy, handing back the two things a caller does with it, and turning the merge into the
sentences the agent reading it can act on.

It lives here, in ``services/``, rather than beside the tool that first needed it, because
the lifetime of a fork is no longer the lifetime of a tool call. A delegated run is now a
Run of its own — it outlives the call that launched it, and the merge happens when *it*
ends, from a terminal hook that has no ``RunContext`` and could not reach a tool module
anyway. So the parameters are spelled out rather than read off ``RunDeps``: ``services``
sits below ``tools`` in the dependency order and must not import it.

Every handle is resolved optionally, which is the same degrade every capability-backed
feature makes: a host with no container runtime can still run a sub-agent, it just cannot
give one a workspace of its own, and the caller turns that into a sentence rather than an
exception.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from core.container import ServiceContainer
from core.fork import MergeReport
from services.projects.store import ProjectStore
from services.projects.worktree import WorktreeManager
from services.sandbox import SandboxSessionManager
from services.sandbox.session import LiveWork
from services.workspace import HostFiles, RunWorkspace

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ForkTarget:
    """Where a fork is cut from, and the names the two halves are addressed by.

    ``delegation_id`` names the child for the whole of its life: a worktree fork is merged
    and discarded by (parent conversation, delegation id), so the caller that takes the
    fork and the terminal hook that lands it must agree on this one string. It is stored,
    not re-derived — an id that lived only in the call that asked for the fork is exactly
    how a checkout gets stranded.
    """

    #: The workspace being forked — the parent's own, already resolved by the caller so a
    #: child can never end up on a different filesystem than the agent that launched it.
    parent: RunWorkspace
    #: The parent's workspace key (its conversation, normally), and the child's own.
    parent_key: str
    child_key: str
    delegation_id: str
    owner_id: str
    project_id: str | None = None
    #: The *parent's* conversation — what the worktree manager keys a child checkout on.
    conversation_id: str | None = None


@dataclass
class Fork:
    """A child's workspace and the two things its launcher does with it afterwards.

    ``hold`` is the half that did not exist while delegation was synchronous. A sandbox
    session is claimed by the run using it, so the live-session cap cannot displace it
    mid-work — and displacing a fork means *deleting* it, nothing here being sealed. While
    a delegation blocked its parent's turn the parent's own run was that claim; now the
    child outlives the call that launched it, so the claim has to move to the child's run
    as soon as there is one. A worktree fork has no such cap, and its ``hold`` is a no-op
    rather than a second code path at every call site.
    """

    workspace: RunWorkspace
    merge: Callable[[], Awaitable[MergeReport]]
    discard: Callable[[], Awaitable[None]]
    hold: Callable[[LiveWork], None]


async def fork_workspace(
    caps: ServiceContainer, target: ForkTarget, *, holder: LiveWork | None = None
) -> Fork | None:
    """The child's workspace, forked the way its kind is forked.

    ``None`` when the handles that would do it are absent — the same degrade every
    capability-backed feature makes. Raising is reserved for a fork that *should* have
    worked and didn't; the caller reports either as a sentence.
    """
    if target.parent.kind == "worktree":
        return await _fork_worktree(caps, target)
    return await _fork_sandbox(caps, target, holder=holder)


async def _fork_sandbox(
    caps: ServiceContainer, target: ForkTarget, *, holder: LiveWork | None
) -> Fork | None:
    sessions = caps.get_optional(SandboxSessionManager)
    if sessions is None:
        return None
    session = await sessions.fork(target.parent_key, target.child_key, holder=holder)
    return Fork(
        workspace=RunWorkspace(root=session.ensure_workspace(), kind="sandbox", files=session),
        merge=lambda: sessions.merge_back(target.child_key, target.parent_key),
        discard=lambda: sessions.purge(target.child_key),
        hold=session.hold,
    )


async def _fork_worktree(caps: ServiceContainer, target: ForkTarget) -> Fork | None:
    projects = caps.get_optional(ProjectStore)
    worktrees = caps.get_optional(WorktreeManager)
    if projects is None or worktrees is None or not target.project_id or not target.conversation_id:
        return None
    project = await projects.get(target.owner_id, target.project_id)
    root = Path(project.root_path)
    where = {
        "project_id": target.project_id,
        "root": root,
        "conversation_id": target.conversation_id,
        "delegation_id": target.delegation_id,
    }
    state = await worktrees.fork(**where)
    return Fork(
        workspace=RunWorkspace(
            root=state.path,
            kind="worktree",
            files=HostFiles(state.path),
            branch=state.branch,
        ),
        merge=lambda: worktrees.merge_back(**where),
        discard=lambda: worktrees.discard_child(**where),
        # A checkout is not subject to the live-session cap, so nothing claims it.
        hold=lambda _: None,
    )


def merge_summary(report: MergeReport) -> str:
    """What came back, in the words the agent reading it needs to act on it.

    Conflicts and deletions are named rather than counted: "three files conflicted" is
    not something the agent reading this can do anything with, and the whole point of
    refusing to overwrite is that somebody decides afterwards which version is right.

    What it does *not* say is "compare the two versions". The fork goes away with the
    delegation either way, so the sub-agent's side of a conflict survives as its report
    and nowhere else, and pointing the parent at a copy that is gone costs it a turn
    discovering that.
    """
    lines = [
        "Merged back into your workspace: "
        + (", ".join(report.files) if report.files else "nothing.")
    ]
    if report.conflicts:
        lines.append(
            "Not merged — you changed these while the sub-agent ran, so your versions "
            "stand: "
            + ", ".join(report.conflicts)
            + ". Its copy is gone with the fork; if you still want its change, make it "
            "yourself from what it reported above."
        )
    if report.deleted:
        # Named on their own line rather than folded into the merged files: "your file
        # changed" and "your file is gone" are not the same sentence, and what a deletion
        # did to the parent differs by workspace kind (`core/fork.py`).
        lines.append("Deleted by the sub-agent: " + ", ".join(report.deleted))
    return "\n".join(lines)
