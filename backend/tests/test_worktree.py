"""Worktrees, against real git.

Mocking git here would test nothing worth testing — the whole point of this layer is
that a real `git worktree add` behaves, that a branch can be checked out twice in a way
git accepts, and that the operator's own tree is genuinely untouched. So these drive the
real binary in a temporary repository.

The load-bearing assertion is the last one: after the agent has edited and committed in
its worktree, the operator's checkout still reads exactly what it did before.
"""

from __future__ import annotations

import asyncio

import pytest

from core.exceptions import InvalidInputError
from services.projects.worktree import (
    WorktreeBusyError,
    WorktreeManager,
    branch_for,
)


async def _run(cwd, *args: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=str(cwd),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.communicate()


async def _repo(tmp_path):
    """A real repository with one commit."""
    root = tmp_path / "project"
    root.mkdir()
    (root / "hello.txt").write_text("original\n")
    await _run(root, "git", "init", "-b", "main")
    await _run(root, "git", "add", "-A")
    await _run(
        root,
        "git",
        "-c",
        "user.name=T",
        "-c",
        "user.email=t@e",
        "commit",
        "-m",
        "first",
    )
    return root


def _manager(tmp_path) -> WorktreeManager:
    return WorktreeManager(tmp_path / "worktrees")


class TestEnsureRepo:
    async def test_refuses_to_init_without_confirmation(self, tmp_path):
        plain = tmp_path / "plain"
        plain.mkdir()
        # Creating a repository in someone's directory is a real side effect; it must
        # never happen as a side effect of starting a chat.
        with pytest.raises(InvalidInputError):
            await _manager(tmp_path).ensure_repo(plain, confirmed=False)

    async def test_initialises_when_confirmed(self, tmp_path):
        plain = tmp_path / "plain"
        plain.mkdir()
        (plain / "a.txt").write_text("x")
        manager = _manager(tmp_path)

        assert await manager.ensure_repo(plain, confirmed=True) is True
        assert await manager.is_repo(plain) is True
        # Idempotent — a second call is not a second repository.
        assert await manager.ensure_repo(plain, confirmed=True) is False

    async def test_initialises_an_empty_directory(self, tmp_path):
        # --allow-empty matters: with no files there is no commit to branch a worktree
        # from, and acquire would fail on a project that is merely new.
        empty = tmp_path / "empty"
        empty.mkdir()
        manager = _manager(tmp_path)
        await manager.ensure_repo(empty, confirmed=True)
        state = await manager.acquire(
            project_id="p", root=empty, base_ref="HEAD", conversation_id="c1"
        )
        assert state.path.is_dir()


class TestAcquire:
    async def test_checks_the_branch_out_beside_the_repo(self, tmp_path):
        root = await _repo(tmp_path)
        state = await _manager(tmp_path).acquire(
            project_id="p", root=root, base_ref="main", conversation_id="c1"
        )
        assert state.branch == branch_for("c1")
        assert (state.path / "hello.txt").read_text() == "original\n"
        # Outside the repository, and outside data_dir — the host-command fence denies
        # reads of the whole data directory.
        assert root not in state.path.parents

    async def test_is_idempotent_for_the_same_conversation(self, tmp_path):
        root = await _repo(tmp_path)
        manager = _manager(tmp_path)
        first = await manager.acquire(
            project_id="p", root=root, base_ref="main", conversation_id="c1"
        )
        second = await manager.acquire(
            project_id="p", root=root, base_ref="main", conversation_id="c1"
        )
        assert first.path == second.path

    async def test_refuses_a_second_conversation(self, tmp_path):
        root = await _repo(tmp_path)
        manager = _manager(tmp_path)
        await manager.acquire(
            project_id="p", root=root, base_ref="main", conversation_id="c1"
        )
        # One worktree per project, so two threads cannot interleave edits over one
        # checkout and corrupt each other's picture of the tree.
        with pytest.raises(WorktreeBusyError):
            await manager.acquire(
                project_id="p", root=root, base_ref="main", conversation_id="c2"
            )

    async def test_a_released_project_can_be_taken_by_another_conversation(self, tmp_path):
        root = await _repo(tmp_path)
        manager = _manager(tmp_path)
        await manager.acquire(
            project_id="p", root=root, base_ref="main", conversation_id="c1"
        )
        manager.release("p", "c1")
        state = await manager.acquire(
            project_id="p", root=root, base_ref="main", conversation_id="c2"
        )
        assert state.branch == branch_for("c2")

    async def test_a_non_repo_is_refused(self, tmp_path):
        plain = tmp_path / "plain"
        plain.mkdir()
        with pytest.raises(InvalidInputError):
            await _manager(tmp_path).acquire(
                project_id="p", root=plain, base_ref="HEAD", conversation_id="c1"
            )


class TestDiffAndMerge:
    async def _edited(self, tmp_path):
        root = await _repo(tmp_path)
        manager = _manager(tmp_path)
        state = await manager.acquire(
            project_id="p", root=root, base_ref="main", conversation_id="c1"
        )
        (state.path / "hello.txt").write_text("changed by the agent\n")
        await _run(state.path, "git", "add", "-A")
        await _run(
            state.path,
            "git",
            "-c",
            "user.name=A",
            "-c",
            "user.email=a@e",
            "commit",
            "-m",
            "agent edit",
        )
        return root, manager, state

    async def test_the_operators_tree_is_untouched_until_they_merge(self, tmp_path):
        root, manager, _state = await self._edited(tmp_path)

        # THE assertion this whole design exists for.
        assert (root / "hello.txt").read_text() == "original\n"

        await manager.merge(root, base_ref="main", conversation_id="c1")
        assert (root / "hello.txt").read_text() == "changed by the agent\n"

    async def test_diff_reports_what_changed(self, tmp_path):
        root, manager, _state = await self._edited(tmp_path)
        diff = await manager.diff(root, base_ref="main", conversation_id="c1")
        assert diff.files_changed == 1
        assert diff.insertions == 1
        assert diff.deletions == 1
        assert "changed by the agent" in diff.patch

    async def test_discard_removes_the_branch(self, tmp_path):
        root, manager, _state = await self._edited(tmp_path)
        await manager.discard(root, project_id="p", conversation_id="c1")
        # And the operator's tree still never saw it.
        assert (root / "hello.txt").read_text() == "original\n"
        assert manager.holder("p") is None
