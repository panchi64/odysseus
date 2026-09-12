"""One workspace-key convention, honoured by both workspace kinds.

A workspace key has always been able to name a *delegation* of a workspace rather than the
workspace itself — a forked sandbox is keyed ``<parent>/<child>`` — but only the sandbox
half read it that way. The worktree half keyed off the conversation instead, which is why a
delegated run in code mode could be handed its own container and never its own checkout:
its conversation does not hold the project, so it was refused as a rival for it.

These hold the two halves of that: that the split is read the same way everywhere, and that
an ordinary run — whose key *is* its conversation — resolves exactly as it did before.
"""

from __future__ import annotations

import asyncio

from services.projects.repo import child_branch_for
from services.projects.worktree import WorktreeManager
from services.workspace import split_workspace_key


async def _run(cwd, *args: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=str(cwd),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.communicate()


async def _repo(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "hello.txt").write_text("original\n")
    await _run(root, "git", "init", "-b", "main")
    await _run(root, "git", "add", "-A")
    await _run(
        root, "git", "-c", "user.name=T", "-c", "user.email=t@e", "commit", "-m", "first"
    )
    return root


class TestSplittingAKey:
    def test_a_plain_key_names_its_own_workspace(self):
        assert split_workspace_key("c123") == ("c123", None)

    def test_a_delegated_key_names_the_parents_workspace_and_the_delegation(self):
        assert split_workspace_key("c123/w7") == ("c123", "w7")

    def test_an_empty_key_names_nothing(self):
        # A stateless run has no conversation to key on; the caller falls back rather
        # than resolving a workspace for the empty string.
        assert split_workspace_key("") == ("", None)

    def test_a_trailing_separator_is_not_a_delegation(self):
        # Otherwise a key built by joining an empty id would silently resolve to a
        # *different* checkout than the conversation's own.
        assert split_workspace_key("c123/") == ("c123", None)


class TestOpeningAChildCheckout:
    async def _held(self, tmp_path):
        root = await _repo(tmp_path)
        manager = WorktreeManager(tmp_path / "worktrees")
        parent = await manager.acquire(
            project_id="p", root=root, base_ref="main", conversation_id="c1"
        )
        return root, manager, parent

    async def test_a_child_opens_beside_its_parent_without_taking_the_project(
        self, tmp_path
    ):
        root, manager, parent = await self._held(tmp_path)
        (parent.path / "hello.txt").write_text("mid-edit\n")

        child = await manager.open_child(
            project_id="p", root=root, conversation_id="c1", delegation_id="d1"
        )

        assert child.path != parent.path
        assert child.branch == child_branch_for("c1", "d1")
        # It opens on what the parent's transcript describes, not on the last commit.
        assert (child.path / "hello.txt").read_text() == "mid-edit\n"
        # And the parent still holds the project: a sub-agent working beside the thread
        # that launched it is one conversation in two places, not a second thread.
        assert manager.holder("p") == "c1"

    async def test_reopening_keeps_the_childs_own_work(self, tmp_path):
        root, manager, _parent = await self._held(tmp_path)
        child = await manager.open_child(
            project_id="p", root=root, conversation_id="c1", delegation_id="d1"
        )
        (child.path / "wip.txt").write_text("half-done\n")

        again = await manager.open_child(
            project_id="p", root=root, conversation_id="c1", delegation_id="d1"
        )

        # THE assertion: a sub-agent resolves its workspace on every file-tool call, so
        # the second answer has to be the same checkout with its work still in it.
        assert again.path == child.path
        assert (again.path / "wip.txt").read_text() == "half-done\n"

    async def test_reopening_does_not_commit_the_parent_again(self, tmp_path):
        root, manager, parent = await self._held(tmp_path)
        await manager.open_child(
            project_id="p", root=root, conversation_id="c1", delegation_id="d1"
        )
        before = await _log(parent.path)

        for _ in range(3):
            await manager.open_child(
                project_id="p", root=root, conversation_id="c1", delegation_id="d1"
            )

        # Cutting a fork commits the parent's working tree so the child opens on it.
        # Doing that per resolution would be a commit per tool call on the operator's
        # branch — which is the whole reason this is not just `fork`.
        assert await _log(parent.path) == before

    async def test_two_children_of_one_parent_get_their_own_checkouts(self, tmp_path):
        root, manager, _parent = await self._held(tmp_path)

        one = await manager.open_child(
            project_id="p", root=root, conversation_id="c1", delegation_id="d1"
        )
        two = await manager.open_child(
            project_id="p", root=root, conversation_id="c1", delegation_id="d2"
        )

        # Parallel sub-agents are the ordinary case now — the model launches several in
        # one step — so two of them must never land in one working tree.
        assert one.path != two.path


async def _log(path) -> str:
    proc = await asyncio.create_subprocess_exec(
        "git",
        "log",
        "--oneline",
        cwd=str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    return out.decode()
