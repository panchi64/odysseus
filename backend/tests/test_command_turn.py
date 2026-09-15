"""A turn sent with a slash command: what the model gets, and what is written down.

The whole design rests on those two being different. The operator's literal `/reviewer
check the auth path` is their turn and persists; the expansion rides the tail of the same
user prompt and is stripped before the turn is recorded. If either half of that stops
being true the feature is either useless (the model never learns what the command meant)
or corrosive (an old expansion replays forever, and a reviewer reads repo-authored text
under the operator's own label).
"""

from __future__ import annotations

from ._helpers import client_app, collect_sse_events, patch_model_resolution


async def _turn(
    client, prompt: str, command: dict | None = None
) -> tuple[list[dict], str]:
    """Run one turn to its end; hand back its events and the thread it landed in."""
    payload: dict = {"prompt": prompt}
    if command is not None:
        payload["command"] = command
    resp = await client.post("/chat", json=payload)
    assert resp.status_code == 202, resp.text
    created = resp.json()
    return await collect_sse_events(client, created["run_id"]), created["conversation_id"]


def _injections(events: list[dict]) -> list[dict]:
    return [e for e in events if e["type"] == "context.injected"]


class TestTheExpansionReachesTheModel:
    async def test_an_agent_command_is_announced_as_tail_context(self, monkeypatch):
        patch_model_resolution(monkeypatch)
        async with client_app() as (client, _app):
            events, _ = await _turn(
                client,
                "/reviewer check the auth path",
                {"name": "reviewer", "argument": "check the auth path"},
            )
        rows = [e for e in _injections(events) if e["contributor"] == "command"]
        assert len(rows) == 1, "announced exactly once, under a fixed slug"
        # The tail, never the head: a command body differs per turn, and a volatile block
        # at the head invalidates the whole cached prefix behind it.
        assert rows[0]["placement"] == "prompt"
        assert "subagents_launch" in rows[0]["text"]
        assert "check the auth path" in rows[0]["text"]

    async def test_a_skill_command_directs_the_model_to_open_it(self, monkeypatch):
        patch_model_resolution(monkeypatch)
        async with client_app() as (client, _app):
            created = await client.post(
                "/skills", json={"name": "release-notes", "description": "d", "body": "b"}
            )
            await client.post(f"/skills/{created.json()['id']}/publish")
            events, _ = await _turn(
                client, "/release-notes", {"name": "release-notes", "argument": ""}
            )
        row = next(e for e in _injections(events) if e["contributor"] == "command")
        assert "skills_open" in row["text"]

    async def test_a_turn_with_no_command_announces_none(self, monkeypatch):
        patch_model_resolution(monkeypatch)
        async with client_app() as (client, _app):
            events, _ = await _turn(client, "say hi")
        assert not [e for e in _injections(events) if e["contributor"] == "command"]


class TestWhatIsWrittenDown:
    async def test_the_turn_on_record_is_the_literal_text(self, monkeypatch):
        patch_model_resolution(monkeypatch)
        async with client_app() as (client, _app):
            _events, conversation_id = await _turn(
                client,
                "/reviewer check the auth path",
                {"name": "reviewer", "argument": "check the auth path"},
            )
            detail = (await client.get(f"/conversations/{conversation_id}")).json()

        user_turns = [m for m in detail["messages"] if m["role"] == "user"]
        assert len(user_turns) == 1
        # Exactly what they typed — not the expansion, and not the two concatenated.
        assert user_turns[0]["content"] == "/reviewer check the auth path"
        assert "subagents_launch" not in user_turns[0]["content"]


class TestResolutionFailure:
    async def test_an_unknown_command_still_sends_the_turn(self, monkeypatch):
        patch_model_resolution(monkeypatch)
        async with client_app() as (client, _app):
            # The catalog narrows on facts that move between the picker's read and the
            # send. Failing the turn would throw away the operator's message to punish
            # them for a race they did not cause.
            events, _ = await _turn(
                client, "/gone now what", {"name": "gone", "argument": "now what"}
            )
        assert events[-1]["type"] == "run.ended"
        assert not [e for e in _injections(events) if e["contributor"] == "command"]

    async def test_a_command_the_thread_is_not_offered_expands_to_nothing(self, monkeypatch):
        patch_model_resolution(monkeypatch)
        async with client_app() as (client, _app):
            # `compact` needs a conversation to act on; it is also an action, which never
            # composes a turn at all. Either way there is nothing to put in the tail.
            events, _ = await _turn(
                client, "/compact", {"name": "compact", "argument": ""}
            )
        assert not [e for e in _injections(events) if e["contributor"] == "command"]
