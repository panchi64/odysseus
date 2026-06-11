"""Per-conversation live sandboxes: selective sealing, lazy acquisition, the idle
reaper, and (with a runtime) file continuity across calls and across a reap."""

from __future__ import annotations

import pytest

from core.config import Settings
from core.vault import Vault
from services.sandbox import (
    ContainerSandbox,
    SandboxError,
    SandboxSessionManager,
    SandboxSpec,
)
from services.sandbox.session import (
    _excluded,
    _restore_workspace,
    _safe_key,
    _seal_workspace,
)

from .test_sandbox import _runtime_ready

_EXCLUDES = Settings().sandbox_session_seal_excludes


async def _vault(tmp_path) -> Vault:
    vault = Vault(tmp_path / "keyfile.json")
    await vault.setup("pw")
    return vault


def _manager(tmp_path, vault, **overrides) -> SandboxSessionManager:
    opts = dict(
        data_dir=tmp_path,
        idle_ttl_s=1800.0,
        reap_interval_s=60.0,
        excludes=_EXCLUDES,
    )
    opts.update(overrides)
    return SandboxSessionManager(ContainerSandbox(), vault, **opts)


# --- naming + exclusion ------------------------------------------------------
def test_safe_key_is_container_safe():
    key = _safe_key("conv/../weird id!")
    assert key.startswith("s")
    assert all(c.isalnum() or c in "_.-" for c in key)


def test_excluded_drops_envs_and_caches_only():
    assert _excluded(".venv", _EXCLUDES)
    assert _excluded("pkg/__pycache__/x.pyc", _EXCLUDES)
    assert _excluded("node_modules", _EXCLUDES)
    assert not _excluded("analysis.py", _EXCLUDES)
    assert not _excluded("output/chart.png", _EXCLUDES)


# --- sealing keeps the agent's files, drops the bloat ------------------------
async def test_seal_round_trip_keeps_files_drops_bloat(tmp_path):
    vault = await _vault(tmp_path)
    work = tmp_path / "work"
    (work / "sub").mkdir(parents=True)
    (work / "analysis.py").write_text("print('hi')")
    (work / "sub" / "out.txt").write_text("result")
    (work / ".venv" / "lib").mkdir(parents=True)
    (work / ".venv" / "lib" / "big.so").write_bytes(b"x" * 1000)
    (work / "__pycache__").mkdir()
    (work / "__pycache__" / "m.pyc").write_bytes(b"junk")

    sealed = _seal_workspace(work, _EXCLUDES, vault)
    restored = tmp_path / "restored"
    _restore_workspace(sealed, restored, vault)

    assert (restored / "analysis.py").read_text() == "print('hi')"
    assert (restored / "sub" / "out.txt").read_text() == "result"
    assert not (restored / ".venv").exists()  # virtual env dropped
    assert not (restored / "__pycache__").exists()  # cache dropped


# --- errors surface legibly, never as a crash --------------------------------
async def test_run_wraps_an_unexpected_error_as_sandbox_error(tmp_path, monkeypatch):
    vault = await _vault(tmp_path)
    session = await _manager(tmp_path, vault).acquire("conv-a")

    def boom() -> None:
        raise ValueError("something deep broke")

    monkeypatch.setattr(session, "_ensure_workspace", boom)
    with pytest.raises(SandboxError):  # the agent gets a sandbox failure, not a ValueError
        await session.run(SandboxSpec(command=["echo", "hi"]))


async def test_restoring_a_damaged_seal_raises_sandbox_error(tmp_path):
    vault = await _vault(tmp_path)
    with pytest.raises(SandboxError):
        _restore_workspace(b"not a valid sealed archive", tmp_path / "out", vault)


# --- lazy acquisition --------------------------------------------------------
async def test_acquire_is_lazy_and_idempotent_per_key(tmp_path):
    vault = await _vault(tmp_path)
    manager = _manager(tmp_path, vault)
    first = await manager.acquire("conv-a")
    again = await manager.acquire("conv-a")
    other = await manager.acquire("conv-b")
    assert first is again  # same conversation reuses its session
    assert other is not first
    # Lazy: no container or workspace exists yet, just the bookkeeping object.
    assert not first.workspace.exists()


# --- the idle reaper ---------------------------------------------------------
async def test_reaper_seals_then_drops_an_idle_session(tmp_path):
    vault = await _vault(tmp_path)
    manager = _manager(tmp_path, vault, idle_ttl_s=0.0)
    session = await manager.acquire("conv-a")
    session.workspace.mkdir(parents=True, exist_ok=True)
    (session.workspace / "notes.txt").write_text("keep me")

    await manager._sweep()

    assert not manager._sessions  # reaped from the registry
    assert session.sealed.exists()  # files preserved, encrypted
    assert not session.workspace.exists()  # plaintext cleared

    # Resuming the conversation restores the kept files into a fresh session.
    revived = await manager.acquire("conv-a")
    revived._ensure_workspace()
    assert (revived.workspace / "notes.txt").read_text() == "keep me"


async def test_start_stop_manages_the_reaper_task(tmp_path):
    vault = await _vault(tmp_path)
    manager = _manager(tmp_path, vault)
    await manager.start()
    assert manager._reaper is not None
    await manager.stop()  # cancels the reaper and tears down any live sessions
    assert manager._reaper is None


async def test_reaper_spares_fresh_and_busy_sessions(tmp_path):
    vault = await _vault(tmp_path)
    fresh_mgr = _manager(tmp_path / "a", vault, idle_ttl_s=3600.0)
    await fresh_mgr.acquire("conv-a")
    await fresh_mgr._sweep()
    assert fresh_mgr._sessions  # within TTL → spared

    busy_mgr = _manager(tmp_path / "b", vault, idle_ttl_s=0.0)
    session = await busy_mgr.acquire("conv-b")
    await session._lock.acquire()  # simulate a call in flight
    try:
        await busy_mgr._sweep()
        assert busy_mgr._sessions  # never reaped mid-run, even past TTL
    finally:
        session._lock.release()


# --- live container (only when a real runtime is present) --------------------
@pytest.mark.skipif(not _runtime_ready(), reason="no usable container runtime")
async def test_live_session_persists_files_across_calls(tmp_path):
    vault = await _vault(tmp_path)
    manager = _manager(tmp_path, vault)
    try:
        session = await manager.acquire("conv-a")
        wrote = await session.run(
            SandboxSpec(command=["bash", "-c", "echo persisted > note.txt"], timeout_s=60)
        )
        assert wrote.ok
        # A later call in the same session sees the file the earlier one wrote.
        read = await session.run(
            SandboxSpec(command=["bash", "-c", "cat note.txt"], timeout_s=60)
        )
        assert "persisted" in read.stdout
    finally:
        await manager.stop()
