"""Git worktrees — where coding mode actually works.

The operator's checkout is never written to. A coding conversation gets a **branch**
(``ody/<conversation-id>``) checked out in a worktree beside the repository, the agent
edits and runs tests there, and the only thing that ever touches the operator's own tree
is an explicit merge they ask for.

Three decisions here are load-bearing and none of them is obvious from the code.

**One worktree per project, not per conversation.** A worktree is a full checkout, so
per-conversation would mean a fresh ``node_modules`` / ``.venv`` / build cache for every
thread — minutes of reinstall before the agent does anything useful, and no reap policy
short of deleting the thread. Sharing one per project keeps those caches warm, which is
most of the reason to code on the host at all. The cost is that only one coding
conversation can hold a project at a time; that is enforced rather than allowed to
silently interleave two threads over one checkout.

**Worktrees live outside ``data_dir``.** An approved host command is fenced by
``services/sandbox/host.py``, which denies reads of the whole data directory — the vault,
the sealed workspaces and the database are in there. A worktree beneath it would be
unreadable by the very shell that has to build and test it. The consequence is that a
worktree is plaintext on disk; it is a checkout of the operator's own already-plaintext
repository, so it exposes nothing that was not already exposed.

**``git init`` is never implicit.** Creating a repository in someone's directory is a
real, visible side effect. `ensure_repo` performs it, but only when the caller has an
explicit confirmation from the operator — the Projects UI asks at project-creation time,
not the agent mid-turn.

A last thing worth knowing because it will otherwise be discovered halfway through a
session: a worktree branches from the project's base ref, so **uncommitted work in the
operator's own checkout is invisible to the agent**. `RepoProbe.uncommitted_changes`
exists so the UI can say so up front.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from core.exceptions import InvalidInputError

logger = logging.getLogger(__name__)

#: Branch namespace. One per coding conversation, so a branch is self-describing and a
#: stale one is obvious.
BRANCH_PREFIX = "ody/"


class WorktreeBusyError(Exception):
    """Another coding conversation is holding this project's worktree.

    Refused rather than queued or silently shared: two threads interleaving edits over
    one checkout would corrupt both their mental models of the tree.
    """


class WorktreeError(Exception):
    """A git operation failed, with git's own message."""


@dataclass(frozen=True)
class WorktreeState:
    path: Path
    branch: str
    base_ref: str


@dataclass(frozen=True)
class Diff:
    """What a coding conversation has changed, against the project's base ref."""

    branch: str
    files_changed: int
    insertions: int
    deletions: int
    patch: str


async def _git(cwd: Path, *args: str) -> tuple[int, str, str]:
    """One git invocation. Fixed argv, no shell — a project path is operator content and
    must never be word-split or interpolated into a command line."""
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    return (
        proc.returncode or 0,
        out.decode("utf-8", "replace"),
        err.decode("utf-8", "replace"),
    )


async def _git_ok(cwd: Path, *args: str) -> str:
    code, out, err = await _git(cwd, *args)
    if code != 0:
        raise WorktreeError((err or out).strip() or f"git {' '.join(args)} failed")
    return out


def branch_for(conversation_id: str) -> str:
    return f"{BRANCH_PREFIX}{conversation_id}"


class WorktreeManager:
    """Owns each project's single worktree and which conversation holds it."""

    def __init__(self, worktrees_dir: Path) -> None:
        self._root = worktrees_dir
        # project_id -> conversation_id currently holding the checkout.
        self._holders: dict[str, str] = {}
        self._lock = asyncio.Lock()

    def path_for(self, project_id: str) -> Path:
        return self._root / project_id

    def holder(self, project_id: str) -> str | None:
        return self._holders.get(project_id)

    def release(self, project_id: str, conversation_id: str) -> None:
        """Give up the checkout if this conversation holds it. Idempotent."""
        if self._holders.get(project_id) == conversation_id:
            del self._holders[project_id]

    async def is_repo(self, root: Path) -> bool:
        code, _, _ = await _git(root, "rev-parse", "--is-inside-work-tree")
        return code == 0

    async def ensure_repo(self, root: Path, *, confirmed: bool) -> bool:
        """Make ``root`` a git repository, returning whether we created one.

        ``confirmed`` is the operator's explicit yes. Without it this refuses rather
        than initialising: committing someone's entire directory into a new repository
        is not something to discover after the fact.
        """
        if await self.is_repo(root):
            return False
        if not confirmed:
            raise InvalidInputError(
                f"{root} is not a git repository. Coding mode needs one so your work can "
                "be kept separate — confirm to create it."
            )
        await _git_ok(root, "init")
        await _git_ok(root, "add", "-A")
        # `--allow-empty` so an empty directory still gets the base commit a worktree
        # must branch from.
        await _git_ok(
            root,
            "-c",
            "user.name=Odysseus",
            "-c",
            "user.email=odysseus@localhost",
            "commit",
            "--allow-empty",
            "-m",
            "Initial commit",
        )
        logger.info("projects: initialised a git repository at %s", root)
        return True

    async def acquire(
        self, *, project_id: str, root: Path, base_ref: str, conversation_id: str
    ) -> WorktreeState:
        """Check this conversation's branch out in the project's worktree.

        Idempotent for the conversation already holding it; refuses while another one
        does. Creating the branch and the worktree are both idempotent, so a restart or
        a second turn in the same thread simply re-acquires.
        """
        async with self._lock:
            holder = self._holders.get(project_id)
            if holder is not None and holder != conversation_id:
                raise WorktreeBusyError(
                    "Another coding conversation is currently working in this project. "
                    "Finish or merge that one first."
                )

            if not await self.is_repo(root):
                raise InvalidInputError(
                    f"{root} is not a git repository — open the project's page to set "
                    "one up."
                )

            branch = branch_for(conversation_id)
            path = self.path_for(project_id)
            path.parent.mkdir(parents=True, exist_ok=True)

            # Branch first (idempotent): `worktree add` on an existing branch must not
            # try to create it again.
            code, _, _ = await _git(root, "rev-parse", "--verify", branch)
            if code != 0:
                await _git_ok(root, "branch", branch, base_ref)

            if (path / ".git").exists():
                # The worktree exists; just move it onto this conversation's branch.
                await _git_ok(path, "checkout", branch)
            else:
                # A directory left behind by a previous run with no .git is not a
                # worktree — remove the registration and re-add rather than failing.
                await _git(root, "worktree", "prune")
                await _git_ok(root, "worktree", "add", str(path), branch)

            self._holders[project_id] = conversation_id
            return WorktreeState(path=path, branch=branch, base_ref=base_ref)

    async def diff(self, root: Path, *, base_ref: str, conversation_id: str) -> Diff:
        """What this conversation changed, as a patch plus a shortstat."""
        branch = branch_for(conversation_id)
        # Three dots: changes on the branch since it diverged, not changes the base has
        # made since — the operator wants to review the agent's work, not their own.
        spec = f"{base_ref}...{branch}"
        patch = await _git_ok(root, "diff", spec)
        stat = await _git_ok(root, "diff", "--shortstat", spec)
        return Diff(
            branch=branch,
            files_changed=_stat_field(stat, "file"),
            insertions=_stat_field(stat, "insertion"),
            deletions=_stat_field(stat, "deletion"),
            patch=patch,
        )

    async def merge(self, root: Path, *, base_ref: str, conversation_id: str) -> str:
        """Land the branch on the base ref — the one operation that writes the
        operator's own tree, and the reason it is approval-gated above this layer."""
        branch = branch_for(conversation_id)
        return await _git_ok(
            root,
            "-c",
            "user.name=Odysseus",
            "-c",
            "user.email=odysseus@localhost",
            "merge",
            "--no-ff",
            branch,
            "-m",
            f"Merged {branch}",
        )

    async def discard(self, root: Path, *, project_id: str, conversation_id: str) -> None:
        """Throw the branch away. Best-effort and idempotent — this runs when a
        conversation is deleted, and a half-set-up thread must not block that."""
        branch = branch_for(conversation_id)
        path = self.path_for(project_id)
        if self._holders.get(project_id) == conversation_id:
            # Park the worktree off the branch so it can be deleted. `--detach` rather
            # than the base ref by name: the base is normally checked out in the *main*
            # working tree, and git refuses to have one branch checked out twice.
            await _git(path, "checkout", "--detach")
            del self._holders[project_id]
        await _git(root, "branch", "-D", branch)


def _stat_field(shortstat: str, word: str) -> int:
    """Pull one number out of `git diff --shortstat`.

    Parsed rather than counted from the patch because the patch may be enormous, and
    git already did the counting. An empty diff yields an empty string, hence the 0.
    """
    for part in shortstat.split(","):
        if word in part:
            digits = "".join(ch for ch in part if ch.isdigit())
            return int(digits) if digits else 0
    return 0
