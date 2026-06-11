"""Live-preview lifecycle on the session manager: token indexing, replacement,
active-view warmth, explicit stop, and teardown on reap/shutdown. The container
launch is faked so these run without a real runtime."""

from __future__ import annotations

import pytest

import services.sandbox.session as session_mod
from core.config import Settings
from core.vault import Vault
from services.sandbox import ContainerSandbox, PreviewHandle, SandboxSessionManager
from services.sandbox.session import _safe_key

_EXCLUDES = Settings().sandbox_session_seal_excludes


async def _vault(tmp_path) -> Vault:
    vault = Vault(tmp_path / "keyfile.json")
    await vault.setup("pw")
    return vault


def _manager(tmp_path, vault, **overrides) -> SandboxSessionManager:
    opts = dict(data_dir=tmp_path, idle_ttl_s=1800.0, reap_interval_s=60.0, excludes=_EXCLUDES)
    opts.update(overrides)
    # Pin a runtime so start_preview gets past the fail-closed check; the launch
    # itself is faked, so no real container is ever created.
    return SandboxSessionManager(ContainerSandbox(runtime="docker"), vault, **opts)


@pytest.fixture
def fake_launch(monkeypatch):
    """Replace the container launch/stop with in-memory fakes; record stops."""
    stopped: list[str] = []

    async def fake_launch_preview(*, container, token, command, port, **_rest):
        return PreviewHandle(
            token=token, container=container, host_port=54321,
            container_port=port, command=tuple(command),
        )

    async def fake_stop(runtime, container):
        stopped.append(container)

    monkeypatch.setattr(session_mod, "launch_preview", fake_launch_preview)
    monkeypatch.setattr(session_mod, "stop_preview_container", fake_stop)
    return stopped


async def test_start_preview_indexes_token_and_resolves(tmp_path, fake_launch):
    mgr = _manager(tmp_path, await _vault(tmp_path))
    handle = await mgr.start_preview("conv-a", ["python", "-m", "http.server", "8000"], 8000)

    assert handle.path == f"/previews/{handle.token}/"
    assert mgr.resolve_preview(handle.token) is handle
    assert mgr.resolve_preview("not-a-real-token") is None


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
    session = mgr._sessions[_safe_key("conv-a")]

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
