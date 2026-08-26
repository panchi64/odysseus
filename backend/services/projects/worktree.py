"""Git worktrees — where coding mode actually works.

The operator's checkout is never written to. A coding conversation gets a **branch**
(``ody/<conversation-id>``) checked out in a worktree beside the repository, the agent
edits and runs tests there, and the only thing that ever touches the operator's own tree
is an explicit merge they ask for.

**The chassis commits, because nothing else does.** The agent edits with its file and
shell tools and has no `git commit` — deliberately: when a body of work becomes a commit
is not a judgement to hand the model. So `snapshot` stages and commits the worktree onto
the conversation's branch, and `diff`/`merge` call it before they read. Skip that and
every downstream step is inert *while looking correct*: a ref-to-ref diff reports nothing
after a session that rewrote ten files, MERGE lands nothing, and the delete gate never
fires. The history is one commit per review rather than one per turn — coarse, but honest
about what it is.

Four more decisions here are load-bearing and none of them is obvious from the code.

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

**A merge releases the project.** The holder map is what enforces one coding thread per
checkout, and `discard` used to be the only thing that cleared it — so a merged thread
kept the project locked forever, and the busy message told the operator to do the very
thing they had just done. Merging hands the project back.

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


#: The identity every commit this layer makes is attributed to. It is the chassis
#: committing on the agent's behalf, and it should read that way in `git log`.
_AUTHOR = ("-c", "user.name=Odysseus", "-c", "user.email=odysseus@localhost")


async def _git(cwd: Path, *args: str) -> tuple[int, str, str]:
    """One git invocation. Fixed argv, no shell — a project path is operator content and
    must never be word-split or interpolated into a command line.

    A missing `cwd` comes back as a failed git call rather than an `OSError`: the
    operator can move or delete a project directory at any time, and every caller here
    already knows how to handle "git said no" while none of them expects an exception
    from a path that existed a moment ago.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except (OSError, NotADirectoryError) as exc:
        return 1, "", f"{cwd} is not reachable: {exc}"
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
                # Commit whatever the previous holder left behind **before** switching.
                # Nothing else commits (see `snapshot`), so the worktree is dirty far more
                # often than not — and `git checkout` carries uncommitted files across, so
                # without this one thread's half-finished work lands on another thread's
                # branch, or the checkout fails outright with a raw git error.
                await self._commit_worktree(path, "Agent changes (carried forward)")
                await _git_ok(path, "checkout", branch)
            else:
                # A directory left behind by a previous run with no .git is not a
                # worktree — remove the registration and re-add rather than failing.
                await _git(root, "worktree", "prune")
                await _git_ok(root, "worktree", "add", str(path), branch)

            self._holders[project_id] = conversation_id
            return WorktreeState(path=path, branch=branch, base_ref=base_ref)

    async def branch_from(self, root: Path, *, source_id: str, conversation_id: str) -> None:
        """Cut this conversation's branch from **another conversation's**, for a fork.

        A forked coding thread inherits a transcript describing files as they are on the
        source's branch, so branching it from the project's base ref instead would hand it
        a tree that contradicts its own history. Raises when the source has no branch —
        the caller treats that as "nothing to inherit" and lets the fork cut its own
        branch from the base ref on its first coding turn, which is correct: there was
        nothing there to preserve.
        """
        await _git_ok(root, "rev-parse", "--verify", branch_for(source_id))
        target = branch_for(conversation_id)
        code, _, _ = await _git(root, "rev-parse", "--verify", target)
        if code == 0:
            return  # already cut — forking twice must not fail the second time
        await _git_ok(root, "branch", target, branch_for(source_id))

    async def snapshot(self, project_id: str, *, conversation_id: str) -> bool:
        """Commit whatever the agent has changed in the worktree onto its branch.

        **Nothing else commits.** The agent edits files with its file and shell tools and
        has no `git commit` of its own — deliberately, because deciding when work is a
        commit is not something to leave to the model. So the chassis commits, and it does
        it here, right before anything wants to *read* the branch. Without this the whole
        chain downstream is inert in a way that looks like it works: `diff` compares two
        refs, so it would report zero changes after a session that rewrote ten files,
        MERGE would land nothing, and deleting the thread would silently discard
        everything the delete gate exists to protect.

        Returns whether it actually committed. Only the conversation that *holds* the
        checkout may snapshot: committing another thread's leftovers onto this branch
        would attribute work to the wrong conversation.
        """
        if self._holders.get(project_id) != conversation_id:
            return False
        return await self._commit_worktree(self.path_for(project_id))

    async def _commit_worktree(self, path: Path, message: str | None = None) -> bool:
        """Stage and commit everything in ``path``, or return False if it was clean.

        Best-effort by design: a worktree that isn't there, or a git that refuses, must
        not take down the read that asked for this. `.odysseus/` ignores itself, so the
        agent's staged attachments and skill bundles never reach the operator's diff.
        """
        if not (path / ".git").exists():
            return False
        await _git(path, "add", "-A")
        # `diff --cached --quiet` exits 0 when nothing is staged — the cheapest way to
        # ask "is there anything to commit" without parsing porcelain.
        clean, _, _ = await _git(path, "diff", "--cached", "--quiet")
        if clean == 0:
            return False
        code, out, err = await _git(
            path, *_AUTHOR, "commit", "-m", message or "Agent changes"
        )
        if code != 0:
            logger.warning("worktree: could not commit %s: %s", path, (err or out).strip())
            return False
        return True

    async def diff(
        self, root: Path, *, base_ref: str, conversation_id: str, project_id: str
    ) -> Diff:
        """What this conversation changed, as a patch plus a shortstat.

        Snapshots first, so what the operator reviews includes the work the agent has
        just done rather than only whatever happened to be committed already."""
        await self.snapshot(project_id, conversation_id=conversation_id)
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

    async def merge(
        self, root: Path, *, base_ref: str, conversation_id: str, project_id: str
    ) -> str:
        """Land the branch on the base ref — the one operation that writes the
        operator's own tree, and the reason the operator presses it themselves.

        **Refuses when their checkout is not on the base ref.** `git merge` lands on
        whatever HEAD happens to be, and the diff they just reviewed was computed against
        `base_ref` — so merging while they sit on some other branch would give them a
        different result from the one they read and approved. Better to say so.

        Snapshots first for the same reason `diff` does, then releases the project so a
        second coding conversation can take it: without that, a project stays locked to
        its first thread forever and the busy message ("finish or merge that one first")
        names an escape that does not work.
        """
        await self.snapshot(project_id, conversation_id=conversation_id)
        await self._require_base_checked_out(root, base_ref)
        branch = branch_for(conversation_id)
        out = await _git_ok(
            root, *_AUTHOR, "merge", "--no-ff", branch, "-m", f"Merged {branch}"
        )
        self.release(project_id, conversation_id)
        return out

    async def _require_base_checked_out(self, root: Path, base_ref: str) -> None:
        """Refuse a merge onto a ref the operator is not actually standing on.

        `HEAD` is the base ref for a repository we never learned a branch name for, and
        it means "wherever you are" — so it always matches. A detached HEAD reports the
        literal string `HEAD` from `--abbrev-ref`, which is *not* a match for a named
        base, and refusing there is right: a merge into a detached HEAD is lost work.
        """
        if base_ref == "HEAD":
            return
        code, current, _ = await _git(root, "rev-parse", "--abbrev-ref", "HEAD")
        if code != 0:
            return  # not a state we can read; let the merge itself report the problem
        current = current.strip()
        if current != base_ref:
            raise WorktreeError(
                f"Your working tree is on {current!r}, but this conversation's changes "
                f"were reviewed against {base_ref!r}. Check out {base_ref!r} first, or "
                "change the project's base ref — merging here would land a different "
                "result from the diff you just read."
            )

    async def discard(self, root: Path, *, project_id: str, conversation_id: str) -> None:
        """Throw the branch away. Best-effort and idempotent — this runs when a
        conversation is deleted, and a half-set-up thread must not block that."""
        branch = branch_for(conversation_id)
        path = self.path_for(project_id)
        if self._holders.get(project_id) == conversation_id:
            # Throw the working tree away with the branch. Without this the discarded
            # thread's uncommitted files survive the checkout below and get carried onto
            # whichever branch is taken up next — the operator said discard, so discard.
            await _git(path, "reset", "--hard")
            await _git(path, "clean", "-fd")
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
