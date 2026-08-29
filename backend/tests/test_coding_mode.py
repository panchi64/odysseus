"""Coding mode over HTTP: the binding, the branch surface, and the delete gate.

The binding is set once and never again, so what these assert is mostly *refusal*: a
coding thread with no project, an ephemeral one, a delete that would silently destroy
unmerged work. Each of those is a state the rest of the system has no answer for, and the
cheapest place to make them impossible is the route that would otherwise create them.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from runs.run import TERMINAL_STATUSES
from tests._helpers import client_app, patch_model_resolution


async def _git(cwd: Path, *args: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=str(cwd),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.communicate()


async def _repo(root: Path) -> Path:
    root.mkdir(parents=True)
    (root / "hello.txt").write_text("original\n")
    await _git(root, "git", "init", "-b", "main")
    await _git(root, "git", "add", "-A")
    await _git(root, "git", "-c", "user.name=T", "-c", "user.email=t@e", "commit", "-m", "first")
    return root


async def _settled(app, run_id: str) -> None:
    """Wait for the turn's run to finish. A live run holds the conversation claim, so a
    delete against it answers 409 for a reason that has nothing to do with branches."""
    for _ in range(400):
        run = app.state.runs.get(run_id)
        if run is None or run.status in TERMINAL_STATUSES:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"run {run_id} never settled")


async def _project(client, tmp_path, name="work") -> dict:
    root = await _repo(tmp_path / name)
    resp = await client.post("/projects", json={"name": name, "rootPath": str(root)})
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestTheBinding:
    async def test_a_coding_thread_needs_a_project(self, tmp_path):
        async with client_app() as (client, _app):
            resp = await client.post("/chat", json={"prompt": "hi", "mode": "coding"})
            assert resp.status_code == 422
            assert "project_id" in resp.text

    async def test_an_ephemeral_thread_cannot_code(self, tmp_path):
        async with client_app() as (client, _app):
            project = await _project(client, tmp_path)
            resp = await client.post(
                "/chat",
                json={
                    "prompt": "hi",
                    "mode": "coding",
                    "project_id": project["id"],
                    "ephemeral": True,
                },
            )
            # A compare pane is scratch; it must not mint a git branch.
            assert resp.status_code == 422

    async def test_an_unknown_project_is_refused_rather_than_filed_nowhere(self):
        async with client_app() as (client, _app):
            resp = await client.post("/chat", json={"prompt": "hi", "project_id": "nope"})
            assert resp.status_code == 404

    async def test_the_binding_is_stored_on_the_thread(self, tmp_path, monkeypatch):
        async with client_app() as (client, app):
            project = await _project(client, tmp_path)
            patch_model_resolution(monkeypatch)
            created = await client.post(
                "/chat",
                json={"prompt": "hi", "mode": "coding", "project_id": project["id"]},
            )
            assert created.status_code == 202, created.text
            conversation_id = created.json()["conversation_id"]

            binding = await app.state.conversations.binding(conversation_id)
            assert binding.mode == "coding"
            assert binding.project_id == project["id"]

    async def test_a_plain_thread_files_itself_under_the_active_project(
        self, tmp_path, monkeypatch
    ):
        async with client_app() as (client, app):
            project = await _project(client, tmp_path)
            await client.post(f"/projects/{project['id']}/activate")
            patch_model_resolution(monkeypatch)
            created = await client.post("/chat", json={"prompt": "hi"})
            conversation_id = created.json()["conversation_id"]

            binding = await app.state.conversations.binding(conversation_id)
            # Filed, but still a chat thread — activating a project must not silently
            # start putting the agent on the operator's host.
            assert binding.project_id == project["id"]
            assert binding.mode == "chat"


class TestTheBranchSurface:
    async def test_a_chat_thread_has_no_branch(self, tmp_path, monkeypatch):
        async with client_app() as (client, _app):
            patch_model_resolution(monkeypatch)
            created = await client.post("/chat", json={"prompt": "hi"})
            conversation_id = created.json()["conversation_id"]
            resp = await client.get(f"/worktrees/{conversation_id}")
            assert resp.status_code == 404

    async def test_a_coding_thread_with_no_work_yet_reports_an_empty_diff(
        self, tmp_path, monkeypatch
    ):
        async with client_app() as (client, _app):
            project = await _project(client, tmp_path)
            patch_model_resolution(monkeypatch)
            created = await client.post(
                "/chat",
                json={"prompt": "hi", "mode": "coding", "project_id": project["id"]},
            )
            conversation_id = created.json()["conversation_id"]

            body = (await client.get(f"/worktrees/{conversation_id}")).json()
            # An empty diff, not an error: a thread that hasn't touched a file is a
            # perfectly normal state and the UI should render zeros for it.
            assert body["branch"] == f"ody/{conversation_id}"
            assert body["filesChanged"] == 0
            assert body["patch"] == ""


class TestDeletingAThread:
    async def _with_work(self, client, app, tmp_path, monkeypatch):
        project = await _project(client, tmp_path)
        patch_model_resolution(monkeypatch)
        created = await client.post(
            "/chat", json={"prompt": "hi", "mode": "coding", "project_id": project["id"]}
        )
        conversation_id = created.json()["conversation_id"]
        await _settled(app, created.json()["run_id"])

        # Do what a coding turn actually does: acquire the worktree and edit files.
        # **No commit** — the agent has no `git commit`, so this is the state every real
        # session is in when the operator opens the diff. Committing here by hand is what
        # made an earlier version of these tests pass against inert code.
        state = await app.state.worktrees.acquire(
            project_id=project["id"],
            root=Path(project["rootPath"]),
            base_ref=project["baseRef"],
            conversation_id=conversation_id,
        )
        (state.path / "hello.txt").write_text("changed by the agent\n")
        return project, conversation_id

    async def test_unmerged_work_refuses_the_delete(self, tmp_path, monkeypatch):
        async with client_app() as (client, app):
            _project_view, conversation_id = await self._with_work(
                client, app, tmp_path, monkeypatch
            )
            resp = await client.delete(f"/conversations/{conversation_id}")
            assert resp.status_code == 409
            assert "unmerged work" in resp.text
            # And the thread is still there to merge from.
            assert (await client.get(f"/worktrees/{conversation_id}")).status_code == 200

    async def test_discard_branch_lets_it_through(self, tmp_path, monkeypatch):
        async with client_app() as (client, app):
            _project_view, conversation_id = await self._with_work(
                client, app, tmp_path, monkeypatch
            )
            resp = await client.delete(f"/conversations/{conversation_id}?discardBranch=true")
            assert resp.status_code == 204

    async def test_merge_lands_it_on_the_operators_tree(self, tmp_path, monkeypatch):
        async with client_app() as (client, app):
            project, conversation_id = await self._with_work(client, app, tmp_path, monkeypatch)
            root = Path(project["rootPath"])
            # Untouched right up until the operator says so — the point of the design.
            assert (root / "hello.txt").read_text() == "original\n"

            diff = (await client.get(f"/worktrees/{conversation_id}")).json()
            assert diff["filesChanged"] == 1

            resp = await client.post(f"/worktrees/{conversation_id}/merge")
            assert resp.status_code == 200, resp.text
            assert (root / "hello.txt").read_text() == "changed by the agent\n"

            # ...and now the thread deletes without a fight, because nothing is unmerged.
            assert (await client.delete(f"/conversations/{conversation_id}")).status_code == 204
