"""Live-preview lifecycle on the session manager: token indexing, replacement,
active-view warmth, explicit stop, and teardown on reap/shutdown. The container
launch is faked so these run without a real runtime."""

from __future__ import annotations

import asyncio
import socket

import pytest

import services.sandbox.preview as preview_mod
import services.sandbox.session as session_mod
from core.config import Settings
from core.vault import Vault
from services.sandbox import ContainerSandbox, PreviewHandle, SandboxSessionManager
from services.sandbox.base import SandboxError, safe_key
from services.sandbox.container import await_http_serving
from services.sandbox.egress_proxy import FORWARD_FILE, FORWARD_PORT

from .conftest import egress_policy

_EXCLUDES = Settings().sandbox_session_seal_excludes


async def _vault(tmp_path) -> Vault:
    vault = Vault(tmp_path / "keyfile.json")
    await vault.setup("pw")
    return vault


def _manager(tmp_path, vault, **overrides) -> SandboxSessionManager:
    opts = dict(
        egress=egress_policy(tmp_path),
        data_dir=tmp_path,
        idle_ttl_s=1800.0,
        reap_interval_s=60.0,
        excludes=_EXCLUDES,
    )
    opts.update(overrides)
    # Pin a runtime so start_preview gets past the fail-closed check; the launch
    # itself is faked, so no real container is ever created.
    return SandboxSessionManager(ContainerSandbox(runtime="docker"), vault, **opts)


class _Stops(list):
    """The preview containers torn down, and — on ``launched`` — the kwargs each launch
    was actually made with. A list subclass so the assertions that only care about the
    teardowns still read as a plain membership check."""

    launched: list[dict]


@pytest.fixture
def fake_launch(monkeypatch):
    """Replace the container launch/stop and the fence's bring-up with in-memory fakes;
    record stops. Records each launch's kwargs so a test can read what the session
    actually asked for."""
    stopped = _Stops()
    launched: list[dict] = []

    async def fake_launch_preview(**kwargs):
        launched.append(kwargs)
        return PreviewHandle(
            token=kwargs["token"],
            container=kwargs["container"],
            host_port=54321,
            container_port=kwargs["port"],
            command=tuple(kwargs["command"]),
        )

    async def fake_stop(runtime, container):
        stopped.append(container)

    async def fake_ensure_up(self) -> None:
        self._running = True
        self._runtime = self._backend.runtime

    monkeypatch.setattr(session_mod, "launch_preview", fake_launch_preview)
    monkeypatch.setattr(session_mod, "stop_preview_container", fake_stop)
    monkeypatch.setattr(session_mod.SandboxSession, "_ensure_up", fake_ensure_up)
    stopped.launched = launched
    return stopped


async def test_start_preview_indexes_token_and_resolves(tmp_path, fake_launch):
    mgr = _manager(tmp_path, await _vault(tmp_path))
    handle = await mgr.start_preview("conv-a", ["python", "-m", "http.server", "8000"], 8000)

    assert handle.path == f"/previews/{handle.token}/"
    assert mgr.resolve_preview(handle.token) is handle
    assert mgr.resolve_preview("not-a-real-token") is None


async def test_preview_joins_the_session_network_behind_the_same_sidecar(tmp_path, fake_launch):
    # A preview is not a hole in the fence: it lands on the conversation's own internal
    # network, with the same proxy env as the exec container, and is reached through the
    # sidecar rather than by publishing a port of its own (it could not — see
    # `services.sandbox.preview`).
    mgr = _manager(tmp_path, await _vault(tmp_path))
    await mgr.start_preview("conv-a", ["srv"], 8000)

    kwargs = fake_launch.launched[0]
    safe = safe_key("conv-a")
    assert kwargs["network"] == f"odysseus-net-{safe}"
    assert kwargs["sidecar"] == f"odysseus-egress-{safe}"
    assert kwargs["allow_dir"] == mgr._egress.allow_dir("conv-a")
    assert kwargs["env"]["HTTPS_PROXY"] == f"http://odysseus-egress-{safe}:3128"


async def test_launch_preview_aims_the_sidecar_at_the_container_it_starts(tmp_path, monkeypatch):
    # The published loopback port belongs to the sidecar, so the only thing that makes it
    # reach *this* preview is the target file — and it has to name the container before
    # the operator's iframe loads, not after.
    calls: list[list[str]] = []

    async def fake_run_subprocess(argv, **_kwargs):
        calls.append(list(argv))
        return False, 0, b"", b""

    async def fake_port(_runtime, container, port):
        return 54321 if (container, port) == ("odysseus-egress-s1", FORWARD_PORT) else 0

    monkeypatch.setattr(preview_mod, "run_subprocess", fake_run_subprocess)
    monkeypatch.setattr(preview_mod, "force_remove_container", _noop_remove)
    monkeypatch.setattr(preview_mod, "published_host_port", fake_port)
    monkeypatch.setattr(preview_mod, "await_listening", _bound)
    monkeypatch.setattr(preview_mod, "await_http_serving", _serving)
    allow_dir = tmp_path / "allow"

    handle = await preview_mod.launch_preview(
        runtime="docker",
        backend=ContainerSandbox(runtime="docker"),
        workspace=tmp_path / "work",
        container="odysseus-pre-s1",
        network="odysseus-net-s1",
        sidecar="odysseus-egress-s1",
        allow_dir=allow_dir,
        token="tok",
        env={"HTTPS_PROXY": "http://odysseus-egress-s1:3128"},
        command=["srv"],
        port=8000,
        startup_timeout_s=1.0,
    )

    assert (allow_dir / FORWARD_FILE).read_text().strip() == "odysseus-pre-s1:8000"
    assert handle.host_port == 54321  # the sidecar's port, not this container's
    joined = " ".join(calls[0])
    assert "--network odysseus-net-s1" in joined
    assert "--publish" not in joined  # an internal network publishes nothing


async def _noop_remove(_runtime, _container, **_kwargs) -> None:
    return None


async def _bound(*_args, **_kwargs) -> None:
    return None  # `await_listening`: the sidecar's published port answered


async def _serving(*_args, **_kwargs) -> bool:
    return True  # `await_http_serving`: something behind the relay answered HTTP


async def test_launch_preview_reports_a_server_that_never_serves(tmp_path, monkeypatch):
    # The published port belongs to the sidecar and has been listening since the session
    # came up, so a dead dev server does not show up as a refused connection — only the
    # container being gone tells them apart. Without that check the agent is handed a
    # healthy-looking handle for a command that exited, and never sees why.
    async def fake_run_subprocess(argv, **_kwargs):
        if argv[1] == "logs":
            return False, 0, b"npm ERR! missing script: dev\n", b""
        return False, 0, b"", b""

    async def fake_port(*_args):
        return 54321

    async def not_serving(*_args, **_kwargs) -> bool:
        return False

    async def not_running(*_args, **_kwargs) -> bool:
        return False

    monkeypatch.setattr(preview_mod, "run_subprocess", fake_run_subprocess)
    monkeypatch.setattr(preview_mod, "force_remove_container", _noop_remove)
    monkeypatch.setattr(preview_mod, "published_host_port", fake_port)
    monkeypatch.setattr(preview_mod, "await_listening", _bound)
    monkeypatch.setattr(preview_mod, "await_http_serving", not_serving)
    monkeypatch.setattr(preview_mod, "container_running", not_running)

    with pytest.raises(SandboxError, match="missing script"):
        await preview_mod.launch_preview(
            runtime="docker",
            backend=ContainerSandbox(runtime="docker"),
            workspace=tmp_path / "work",
            container="odysseus-pre-s1",
            network="odysseus-net-s1",
            sidecar="odysseus-egress-s1",
            allow_dir=tmp_path / "allow",
            token="tok",
            env={},
            command=["npm", "run", "dev"],
            port=8000,
            startup_timeout_s=0.1,
        )


async def test_starting_a_second_preview_replaces_the_first(tmp_path, fake_launch):
    mgr = _manager(tmp_path, await _vault(tmp_path))
    first = await mgr.start_preview("conv-a", ["one"], 8000)
    second = await mgr.start_preview("conv-a", ["two"], 8000)

    assert mgr.resolve_preview(first.token) is None  # the old token no longer resolves
    assert mgr.resolve_preview(second.token) is second
    assert first.container in fake_launch  # the old container was torn down


async def test_resolve_preview_keeps_the_session_warm(tmp_path, fake_launch):
    mgr = _manager(tmp_path, await _vault(tmp_path))
    handle = await mgr.start_preview("conv-a", ["srv"], 8000)
    session = mgr._sessions[safe_key("conv-a")]

    session._last_used = 0.0  # pretend it went idle
    mgr.resolve_preview(handle.token)
    assert session._last_used > 0.0  # a proxied request refreshed it


async def test_stop_preview_deindexes_and_tears_down(tmp_path, fake_launch):
    mgr = _manager(tmp_path, await _vault(tmp_path))
    handle = await mgr.start_preview("conv-a", ["srv"], 8000)

    await mgr.stop_preview("conv-a")

    assert mgr.resolve_preview(handle.token) is None
    assert handle.container in fake_launch
    assert mgr._sessions  # the exec session itself survives an explicit stop


async def test_reaping_a_session_stops_its_preview_and_drops_the_token(tmp_path, fake_launch):
    mgr = _manager(tmp_path, await _vault(tmp_path), idle_ttl_s=0.0)
    handle = await mgr.start_preview("conv-a", ["srv"], 8000)

    await mgr._sweep()  # idle past TTL → reaped

    assert not mgr._sessions
    assert mgr.resolve_preview(handle.token) is None
    assert handle.container in fake_launch  # the preview container went down with it


async def test_stop_clears_all_previews(tmp_path, fake_launch):
    mgr = _manager(tmp_path, await _vault(tmp_path))
    handle = await mgr.start_preview("conv-a", ["srv"], 8000)

    await mgr.stop()

    assert mgr.resolve_preview(handle.token) is None
    assert handle.container in fake_launch


# --- HTTP readiness: a bound port is not yet a serving server ----------------
async def test_await_http_serving_returns_once_the_server_answers():
    async def _handle(reader, writer):
        await reader.read(4096)  # drain the request line + headers
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(_handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        # Returns promptly because the server actually responds over HTTP.
        assert await asyncio.wait_for(await_http_serving(port, timeout_s=5.0), timeout=5.0)


async def test_await_http_serving_gives_up_quietly_when_nothing_listens():
    # Bind then close to claim a port nothing is serving on.
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    # It reports the miss (does not raise) after the budget, never hanging — the caller
    # is the one that decides whether a silent server is a slow one or a dead one.
    assert not await asyncio.wait_for(await_http_serving(port, timeout_s=0.4), timeout=3.0)
