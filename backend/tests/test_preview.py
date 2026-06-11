"""The publish_artifact tool: it reads a sandbox file, captures it as an artifact,
and emits artifact.published — degrading gracefully when capabilities are absent."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from pydantic_ai import Agent, DeferredToolRequests
from pydantic_ai.models.function import DeltaToolCall, FunctionModel

from agent import stream_agent_run
from core.db import init_db, make_engine
from core.vault import Vault
from runs import Run, RunStream
from services.artifacts import (
    ArtifactStore,
    ArtifactView,
    artifact_id_from_result,
    format_publish_result,
)
from services.sandbox import SandboxError
from tools import RunDeps, build_agent_toolsets
from tools.preview import preview_toolset


class FakeSession:
    """Serves canned workspace bytes; raises like the real session on a miss."""

    def __init__(self, files: dict[str, bytes]) -> None:
        self._files = files

    def read_file(self, path: str) -> bytes:
        if path not in self._files:
            raise SandboxError(f"no such file: {path!r}")
        return self._files[path]


class FakeSessionManager:
    def __init__(self, files: dict[str, bytes]) -> None:
        self._session = FakeSession(files)

    async def acquire(self, key: str) -> FakeSession:
        return self._session


async def _store(tmp_path) -> ArtifactStore:
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    vault = Vault(tmp_path / "keyfile.json")
    await vault.setup("pw")
    return ArtifactStore(engine, vault)


def _publish_then_finish(path: str, title: str | None):
    """A model that calls publish_artifact once, then answers with text."""

    def _tool_ran(messages) -> bool:
        return any(
            type(part).__name__ == "ToolReturnPart"
            for message in messages
            for part in message.parts
        )

    async def stream_fn(messages, info):
        if _tool_ran(messages):
            yield "done"
        else:
            args = json.dumps({"path": path, "title": title})
            yield {0: DeltaToolCall(name="preview_publish_artifact", json_args=args)}

    return stream_fn


def _run(files, *, store, conversation_id="conv-1", path="chart.png", title="My Chart"):
    sessions = FakeSessionManager(files)
    agent = Agent(
        FunctionModel(stream_function=_publish_then_finish(path, title)),
        deps_type=RunDeps,
        toolsets=build_agent_toolsets({"preview": preview_toolset()}),
        output_type=[str, DeferredToolRequests],
    )
    run = Run(id="r1", kind="chat", owner_id="operator", stream=RunStream())
    deps = RunDeps(
        run=run,
        owner_id="operator",
        sandbox_sessions=sessions,
        artifacts=store,
        conversation_id=conversation_id,
    )
    return agent, run, deps


def _bodies(run: Run):
    return [e.body for e in run.stream.replay()]


async def test_publish_artifact_captures_and_emits(tmp_path):
    store = await _store(tmp_path)
    agent, run, deps = _run({"chart.png": b"\x89PNG\r\n"}, store=store)
    async with agent.iter("make a chart", deps=deps) as agent_run:
        await stream_agent_run(agent_run, run)

    published = next(b for b in _bodies(run) if b.type == "artifact.published")
    assert published.title == "My Chart"
    assert published.kind == "image"
    assert published.filename == "chart.png"
    # The captured bytes are retrievable and scoped to the conversation.
    blob = await store.content("operator", published.artifact_id)
    assert blob.content == b"\x89PNG\r\n"
    listed = await store.list("operator", "conv-1")
    assert [a.id for a in listed] == [published.artifact_id]


async def test_publish_missing_file_reports_and_does_not_publish(tmp_path):
    store = await _store(tmp_path)
    agent, run, deps = _run({}, store=store, path="absent.html")
    async with agent.iter("go", deps=deps) as agent_run:
        await stream_agent_run(agent_run, run)
    assert "artifact.published" not in [b.type for b in _bodies(run)]
    assert await store.list("operator", "conv-1") == []


async def test_publish_unavailable_without_store():
    # No artifact store wired ⇒ graceful degradation, no event.
    agent, run, deps = _run({"x.txt": b"x"}, store=None, path="x.txt")
    async with agent.iter("go", deps=deps) as agent_run:
        await stream_agent_run(agent_run, run)
    assert "artifact.published" not in [b.type for b in _bodies(run)]


def test_publish_result_round_trips_the_artifact_id():
    # The tool's return line carries the id back through saved history so a cold
    # read can re-attach the artifact to its message (producer/parser agree).
    view = ArtifactView(
        id="deadbeef01",
        conversation_id="conv-1",
        title="My Chart",
        filename="chart.png",
        content_type="image/png",
        kind="image",
        size=6,
        created_at=datetime.now(UTC),
    )
    assert artifact_id_from_result(format_publish_result(view)) == "deadbeef01"


def test_artifact_id_from_unrelated_result_is_none():
    assert artifact_id_from_result("Could not read 'x.html': no such file") is None
