"""The unified ``view`` tool — one capability for the conversation's View.

``view_show(file=…)`` captures a static version and emits ``view.version``;
``view_show(serve=…, port=…, path=…)`` runs the live head and emits ``view.live``
with the entry path baked into the url (so a static server's root no longer
renders a directory listing); ``view_close`` emits ``view.live.stopped``. Bad
arg combinations retry; missing capabilities degrade without an event.
"""

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
from services.sandbox import PreviewHandle, SandboxError
from tools import RunDeps, build_agent_toolsets
from tools.view import view_toolset


class FakeSession:
    """Serves canned workspace bytes; raises like the real session on a miss."""

    def __init__(self, files: dict[str, bytes]) -> None:
        self._files = files

    def read_file(self, path: str) -> bytes:
        if path not in self._files:
            raise SandboxError(f"no such file: {path!r}")
        return self._files[path]


class FakeManager:
    """Stands in for the sandbox session manager — files + a live-head launcher."""

    def __init__(self, files: dict[str, bytes] | None = None, *, fail: bool = False) -> None:
        self._session = FakeSession(files or {})
        self.fail = fail
        self.started: list[tuple] = []
        self.stopped: list[str] = []

    async def acquire(self, key: str) -> FakeSession:
        return self._session

    async def start_preview(self, key: str, command: list[str], port: int) -> PreviewHandle:
        self.started.append((key, tuple(command), port))
        if self.fail:
            raise SandboxError("address already in use")
        return PreviewHandle(
            token="tok", container="c", host_port=5000,
            container_port=port, command=tuple(command),
        )

    async def stop_preview(self, key: str) -> None:
        self.stopped.append(key)


async def _store(tmp_path) -> ArtifactStore:
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    vault = Vault(tmp_path / "keyfile.json")
    await vault.setup("pw")
    return ArtifactStore(engine, vault)


def _call_then_finish(args: dict):
    """A model that calls ``view_show`` once with ``args``, then answers with text.
    Ends the loop on either a tool return or a validation retry, so a rejected call
    doesn't spin forever."""

    def _settled(messages) -> bool:
        return any(
            type(part).__name__ in ("ToolReturnPart", "RetryPromptPart")
            for message in messages
            for part in message.parts
        )

    async def stream_fn(messages, info):
        if _settled(messages):
            yield "done"
        else:
            yield {0: DeltaToolCall(name="view_show", json_args=json.dumps(args))}

    return stream_fn


def _close_then_finish():
    def _settled(messages) -> bool:
        return any(
            type(part).__name__ == "ToolReturnPart"
            for message in messages
            for part in message.parts
        )

    async def stream_fn(messages, info):
        if _settled(messages):
            yield "done"
        else:
            yield {0: DeltaToolCall(name="view_close", json_args="{}")}

    return stream_fn


def _run(stream_fn, *, manager, store=None, conversation_id="conv-1"):
    agent = Agent(
        FunctionModel(stream_function=stream_fn),
        deps_type=RunDeps,
        toolsets=build_agent_toolsets({"view": view_toolset()}),
        output_type=[str, DeferredToolRequests],
    )
    run = Run(id="r1", kind="chat", owner_id="operator", stream=RunStream())
    deps = RunDeps(
        run=run,
        owner_id="operator",
        sandbox_sessions=manager,
        artifacts=store,
        conversation_id=conversation_id,
    )
    return agent, run, deps


def _bodies(run: Run):
    return [e.body for e in run.stream.replay()]


async def _drive(agent, run, deps, prompt="go"):
    async with agent.iter(prompt, deps=deps) as agent_run:
        await stream_agent_run(agent_run, run)


# --- static versions (file=) -------------------------------------------------
async def test_show_file_captures_and_emits_version(tmp_path):
    store = await _store(tmp_path)
    manager = FakeManager({"chart.png": b"\x89PNG\r\n"})
    agent, run, deps = _run(
        _call_then_finish({"file": "chart.png", "title": "My Chart"}),
        manager=manager,
        store=store,
    )
    await _drive(agent, run, deps, "make a chart")

    version = next(b for b in _bodies(run) if b.type == "view.version")
    assert version.title == "My Chart"
    assert version.kind == "image"
    assert version.filename == "chart.png"
    blob = await store.content("operator", version.version_id)
    assert blob.content == b"\x89PNG\r\n"
    listed = await store.list("operator", "conv-1")
    assert [v.id for v in listed] == [version.version_id]


async def test_show_missing_file_reports_and_stores_nothing(tmp_path):
    store = await _store(tmp_path)
    manager = FakeManager({})
    agent, run, deps = _run(
        _call_then_finish({"file": "absent.html"}), manager=manager, store=store
    )
    await _drive(agent, run, deps)
    assert "view.version" not in [b.type for b in _bodies(run)]
    assert await store.list("operator", "conv-1") == []


async def test_show_file_unavailable_without_store():
    manager = FakeManager({"x.txt": b"x"})
    agent, run, deps = _run(
        _call_then_finish({"file": "x.txt"}), manager=manager, store=None
    )
    await _drive(agent, run, deps)
    assert "view.version" not in [b.type for b in _bodies(run)]


# --- live head (serve=) ------------------------------------------------------
async def test_show_live_emits_live_with_entry_path():
    manager = FakeManager()
    agent, run, deps = _run(
        _call_then_finish(
            {
                "serve": ["python", "-m", "http.server", "8000"],
                "port": 8000,
                "path": "index.html",
                "title": "Site",
            }
        ),
        manager=manager,
    )
    await _drive(agent, run, deps, "serve it")

    live = next(b for b in _bodies(run) if b.type == "view.live")
    # The entry path is baked into the url — this is the directory-listing fix.
    assert live.url == "/previews/tok/index.html"
    assert live.port == 8000
    assert live.command == "python -m http.server 8000"
    assert live.title == "Site"
    assert live.conversation_id == "conv-1"
    assert manager.started == [("conv-1", ("python", "-m", "http.server", "8000"), 8000)]


async def test_show_live_without_path_points_at_root():
    manager = FakeManager()
    agent, run, deps = _run(
        _call_then_finish({"serve": ["npm", "run", "dev"], "port": 5173}),
        manager=manager,
    )
    await _drive(agent, run, deps, "serve it")
    live = next(b for b in _bodies(run) if b.type == "view.live")
    assert live.url == "/previews/tok/"


async def test_show_live_failure_feeds_back_without_event():
    manager = FakeManager(fail=True)
    agent, run, deps = _run(
        _call_then_finish({"serve": ["bad"], "port": 8000}), manager=manager
    )
    await _drive(agent, run, deps, "serve it")
    assert "view.live" not in [b.type for b in _bodies(run)]
    assert manager.started  # it tried; the error went back to the model as text


async def test_show_live_unavailable_without_sandbox():
    agent, run, deps = _run(
        _call_then_finish({"serve": ["x"], "port": 8000}), manager=None
    )
    await _drive(agent, run, deps, "serve it")
    assert "view.live" not in [b.type for b in _bodies(run)]


# --- close + validation ------------------------------------------------------
async def test_close_emits_live_stopped():
    manager = FakeManager()
    agent, run, deps = _run(_close_then_finish(), manager=manager)
    await _drive(agent, run, deps, "stop it")
    assert any(b.type == "view.live.stopped" for b in _bodies(run))
    assert manager.stopped == ["conv-1"]


async def test_show_both_modes_retries_without_showing_anything(tmp_path):
    # file AND serve is ambiguous → ModelRetry, no view event either way.
    store = await _store(tmp_path)
    manager = FakeManager({"x.html": b"<p>x</p>"})
    agent, run, deps = _run(
        _call_then_finish({"file": "x.html", "serve": ["x"], "port": 8000}),
        manager=manager,
        store=store,
    )
    await _drive(agent, run, deps)
    types = [b.type for b in _bodies(run)]
    assert "view.version" not in types and "view.live" not in types


# --- result round-trip (cold-read re-attach contract) ------------------------
def test_show_result_round_trips_the_version_id():
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


def test_version_id_from_unrelated_result_is_none():
    assert artifact_id_from_result("Could not read 'x.html': no such file") is None
