"""One answer to "where does this run's file work happen".

Four subsystems used to hard-assume the agent's workspace *is* the container sandbox:
the file tools, `code_execute`, attachment staging, and the skills bundler. Each stated
it slightly differently, and one of them — `tools/files.py` — stated the invariant that
made the set coherent: *these tools reach exactly what `code_execute` reaches and nothing
else*.

Coding mode moves the file work to a git worktree on the host. Re-rooting only the file
tools would break that invariant **silently**: the agent would edit a file it cannot run,
attachments would land where its file tools can't see them, and an opened skill's scripts
would point at a container that isn't in play. So the workspace stops being an assumption
scattered across four modules and becomes one resolved value:

    chat mode   → the conversation's sandbox workspace, mounted in the box at ``/work``
    coding mode → the project's git worktree, on the host, addressed by absolute path

:class:`RunWorkspace` carries both halves — the host directory to act on, and
:meth:`RunWorkspace.display`, the path *string the model is told*. Those differ in chat
mode (host `<data>/sandbox/work/<key>/x` is `/work/x` to the model) and are the same in
coding mode, which is exactly the kind of detail that goes wrong when four modules each
build it themselves.

**Attachments and skills stage under ``.odysseus/`` in a worktree.** They have to land
inside it or the file tools can't reach them, and they must not show up as the agent's
work — so :func:`prepare_worktree_workspace` makes that directory ignore itself.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from services.projects.store import ProjectStore
from services.projects.worktree import WorktreeBusyError, WorktreeManager
from services.sandbox import SandboxError, SandboxSessionManager
from services.sandbox.base import contained_path

logger = logging.getLogger(__name__)

#: Where a conversation's sandbox workspace is mounted inside the container. The model is
#: told this, never the host path — the host path means nothing on the other side of the
#: bind mount.
SANDBOX_MOUNT = "/work"

#: Odysseus' own scratch inside a worktree: staged attachments and opened skill bundles.
#: Excluded from git, so the diff the operator reviews is the agent's work and nothing else.
WORKTREE_SCRATCH = ".odysseus"


class WorkspaceFiles(Protocol):
    """The two-method slice staging needs (``services/sandbox/staging.py``'s
    ``_Stageable``). Named structurally so a sandbox session satisfies it as-is and a
    plain host directory needs only the small adapter below."""

    def read_file(self, relpath: str) -> bytes: ...

    def write_file(self, relpath: str, content: bytes) -> None: ...


class HostFiles:
    """`WorkspaceFiles` over a plain directory — the worktree's side of staging.

    Containment is the sandbox's own check, reused rather than re-derived: a staged
    filename is operator content and must not be able to write outside the tree.
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    def read_file(self, relpath: str) -> bytes:
        target = contained_path(self._root, relpath)
        if not target.is_file():
            raise SandboxError(f"no such file in the workspace: {relpath!r}")
        return target.read_bytes()

    def write_file(self, relpath: str, content: bytes) -> None:
        target = contained_path(self._root, relpath)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


@dataclass(frozen=True)
class RunWorkspace:
    """This run's workspace: the host directory, and how a path in it is named aloud."""

    root: Path
    kind: Literal["sandbox", "worktree"]
    files: WorkspaceFiles
    #: The branch a coding run is working on; None in chat mode.
    branch: str | None = None

    @property
    def stage_prefix(self) -> str:
        """Where staged files go, relative to the root. A worktree keeps them out of the
        operator's diff; a sandbox workspace is ours entirely and needs no prefix."""
        return "" if self.kind == "sandbox" else f"{WORKTREE_SCRATCH}/"

    def display(self, relpath: str) -> str:
        """The path string the model is given for ``relpath``.

        The one place the sandbox's bind mount is translated, so a marker, a tool result
        and a staged skill can never name the same file three different ways.
        """
        if self.kind == "sandbox":
            return f"{SANDBOX_MOUNT}/{relpath.lstrip('/')}"
        return str(self.root / relpath)


async def sandbox_workspace(
    sessions: SandboxSessionManager, sandbox_key: str
) -> RunWorkspace:
    """The conversation's container workspace. Raises `SandboxError` when it can't be
    opened (no runtime, a locked vault, an unreadable seal) — the caller degrades."""
    session = await sessions.acquire(sandbox_key)
    return RunWorkspace(root=session.ensure_workspace(), kind="sandbox", files=session)


async def worktree_workspace(
    *,
    projects: ProjectStore,
    worktrees: WorktreeManager,
    owner_id: str,
    project_id: str,
    conversation_id: str,
) -> RunWorkspace:
    """The project's git worktree, with this conversation's branch checked out.

    Idempotent per conversation, and refused (`WorktreeBusyError`) while another coding
    conversation holds the project — one checkout, one thread at a time.
    """
    project = await projects.get(owner_id, project_id)
    root = Path(project.root_path)
    state = await worktrees.acquire(
        project_id=project_id,
        root=root,
        base_ref=project.base_ref,
        conversation_id=conversation_id,
    )
    prepare_worktree_workspace(state.path)
    return RunWorkspace(
        root=state.path,
        kind="worktree",
        files=HostFiles(state.path),
        branch=state.branch,
    )


def prepare_worktree_workspace(path: Path) -> None:
    """Keep Odysseus' own scratch out of the operator's diff.

    The scratch directory ignores *itself*, with a `.gitignore` containing `*` — which
    covers that `.gitignore` too, so the whole directory disappears from `git status` and
    from `git add -A`. Deliberately not `.git/info/exclude`: for a linked worktree that
    file resolves to the **common** git directory, meaning the operator's own repository
    metadata, and this feature's entire premise is that we do not write there.

    Best-effort: failing to write it is untidy (the agent might commit its own scratch),
    never a reason to refuse the turn.
    """
    try:
        scratch = path / WORKTREE_SCRATCH
        scratch.mkdir(parents=True, exist_ok=True)
        ignore = scratch / ".gitignore"
        if not ignore.is_file():
            ignore.write_text("# Odysseus' own scratch — never the operator's work.\n*\n")
    except OSError:
        logger.debug(
            "workspace: could not exclude %s from git", WORKTREE_SCRATCH, exc_info=True
        )


async def resolve_workspace(
    *,
    mode: str,
    project_id: str | None,
    conversation_id: str | None,
    sandbox_key: str,
    owner_id: str,
    sessions: SandboxSessionManager | None,
    projects: ProjectStore | None,
    worktrees: WorktreeManager | None,
) -> RunWorkspace | None:
    """This run's workspace, or None when there isn't one.

    Takes explicit handles rather than a `RunContext` because it is called from both
    sides of a turn: from inside a run (through `tools/workspace.py`) and at composition
    time, before the run exists, to stage attachments. One resolution, two entry points.

    Returns None rather than raising, for the two shapes of "no workspace" the callers
    already handle: coding mode without the pieces it needs, and a sandbox that will not
    open. A busy worktree is *not* one of those — that is a real conflict the operator
    has to see, so `WorktreeBusyError` propagates.
    """
    if mode == "coding":
        # Never fall back to the sandbox. A coding run that quietly got a container
        # workspace would edit files its shell tools are refused access to, and nothing
        # would say why — the failure the one-workspace rule exists to prevent. No
        # worktree means no workspace, and the tool layer says so in words.
        if projects is None or worktrees is None or not project_id or not conversation_id:
            return None
        try:
            return await worktree_workspace(
                projects=projects,
                worktrees=worktrees,
                owner_id=owner_id,
                project_id=project_id,
                conversation_id=conversation_id,
            )
        except WorktreeBusyError:
            raise
        except Exception:
            # A missing project or a git failure degrades to "no workspace" the same way
            # an unavailable sandbox does; the tool layer says so in words.
            logger.warning("workspace: could not open the project worktree", exc_info=True)
            return None
    if sessions is None:
        return None
    try:
        return await sandbox_workspace(sessions, sandbox_key)
    except SandboxError:
        logger.debug("workspace: no sandbox workspace available", exc_info=True)
        return None
