"""A turn carrying `@` file references: what reaches the model, and what does not.

The claim being defended is that a reference is a **reference**. The turn names paths; it
does not read them. That is what keeps an `@` from twenty turns ago pointing at a file
whose old contents are still being replayed, and it is why the marker is trusted content —
there is no file text in it to be untrusted about.
"""

from __future__ import annotations

from pathlib import Path

from tests._helpers import client_app, collect_sse_events, patch_model_resolution
from tests.test_code_mode import _project


def _injections(events: list[dict], contributor: str) -> list[dict]:
    return [
        e
        for e in events
        if e["type"] == "context.injected" and e["contributor"] == contributor
    ]


async def _code_turn(client, project_id: str, refs: list[str]) -> list[dict]:
    resp = await client.post(
        "/chat",
        json={
            "prompt": "look at these",
            "mode": "code",
            "project_id": project_id,
            "file_refs": refs,
        },
    )
    assert resp.status_code == 202, resp.text
    return await collect_sse_events(client, resp.json()["run_id"])


class TestWhatReachesTheModel:
    async def test_a_reference_names_the_path_and_nothing_else(
        self, monkeypatch, tmp_path: Path
    ):
        patch_model_resolution(monkeypatch)
        async with client_app() as (client, _app):
            project = await _project(client, tmp_path)
            events = await _code_turn(client, project["id"], ["hello.txt"])
        rows = _injections(events, "file_refs")
        assert len(rows) == 1
        assert rows[0]["placement"] == "prompt"
        assert "hello.txt" in rows[0]["text"]
        # The file says "original"; a reference that carried its contents would be an
        # injection, and would go stale in history the moment the file changed.
        assert "original" not in rows[0]["text"]
        assert "files_read_file" in rows[0]["text"]

    async def test_a_path_outside_the_workspace_is_dropped(
        self, monkeypatch, tmp_path: Path
    ):
        patch_model_resolution(monkeypatch)
        async with client_app() as (client, _app):
            project = await _project(client, tmp_path)
            events = await _code_turn(
                client, project["id"], ["../../../etc/passwd", "hello.txt"]
            )
        rows = _injections(events, "file_refs")
        assert "passwd" not in rows[0]["text"]
        assert "hello.txt" in rows[0]["text"]

    async def test_a_turn_naming_only_unresolvable_paths_still_sends(
        self, monkeypatch, tmp_path: Path
    ):
        patch_model_resolution(monkeypatch)
        async with client_app() as (client, _app):
            project = await _project(client, tmp_path)
            events = await _code_turn(client, project["id"], ["does/not/exist.ts"])
        # The operator still has their typed message; refusing the turn over a file they
        # can simply mention again is the worse trade.
        assert events[-1]["type"] == "run.ended"
        assert _injections(events, "file_refs") == []

    async def test_a_turn_with_no_references_announces_nothing(
        self, monkeypatch, tmp_path: Path
    ):
        patch_model_resolution(monkeypatch)
        async with client_app() as (client, _app):
            project = await _project(client, tmp_path)
            events = await _code_turn(client, project["id"], [])
        assert _injections(events, "file_refs") == []


class TestWhatIsWrittenDown:
    async def test_the_marker_does_not_persist(self, monkeypatch, tmp_path: Path):
        patch_model_resolution(monkeypatch)
        async with client_app() as (client, _app):
            project = await _project(client, tmp_path)
            resp = await client.post(
                "/chat",
                json={
                    "prompt": "look at these",
                    "mode": "code",
                    "project_id": project["id"],
                    "file_refs": ["hello.txt"],
                },
            )
            conversation_id = resp.json()["conversation_id"]
            await collect_sse_events(client, resp.json()["run_id"])
            detail = (await client.get(f"/conversations/{conversation_id}")).json()

        user_turn = next(m for m in detail["messages"] if m["role"] == "user")
        # The tail is stripped on record, exactly as it is for the per-turn context and
        # a slash command's expansion — so the turn on record is what was typed.
        assert user_turn["content"] == "look at these"
        assert "files_read_file" not in user_turn["content"]
