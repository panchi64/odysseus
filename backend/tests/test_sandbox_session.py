"""Per-conversation live sandboxes: selective sealing, lazy acquisition, the idle
reaper, and (with a runtime) file continuity across calls and across a reap."""

from __future__ import annotations

import asyncio
import time

import pytest

import services.sandbox.session as session_mod
from core.config import Settings
from core.vault import Vault
from services.sandbox import (
    ContainerSandbox,
    PreviewHandle,
    SandboxError,
    SandboxResult,
    SandboxSession,
    SandboxSessionManager,
    SandboxSpec,
)
from services.sandbox.session import (
    ImageWarmup,
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
    backend = overrides.pop("backend", None) or ContainerSandbox()
    opts = dict(
        data_dir=tmp_path,
        idle_ttl_s=1800.0,
        reap_interval_s=60.0,
        excludes=_EXCLUDES,
    )
    opts.update(overrides)
    return SandboxSessionManager(backend, vault, **opts)


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


# --- write_file: staging a file into the workspace (no runtime needed) --------
async def test_write_file_round_trips_through_read_file(tmp_path):
    vault = await _vault(tmp_path)
    session = await _manager(tmp_path, vault).acquire("conv-x")

    session.write_file("attachments/data.csv", b"a,b\n1,2\n")

    assert session.read_file("attachments/data.csv") == b"a,b\n1,2\n"
    assert (session.workspace / "attachments" / "data.csv").read_bytes() == b"a,b\n1,2\n"


async def test_write_file_rejects_a_path_escape(tmp_path):
    vault = await _vault(tmp_path)
    session = await _manager(tmp_path, vault).acquire("conv-x")

    with pytest.raises(SandboxError):
        session.write_file("../escape.txt", b"nope")


async def test_written_file_survives_a_seal_and_restore(tmp_path):
    # A staged file is inside the sealed workspace, so it persists across a reap.
    vault = await _vault(tmp_path)
    session = await _manager(tmp_path, vault).acquire("conv-x")
    session.write_file("attachments/keep.txt", b"hold onto me")

    await session.shutdown()  # seals the workspace and removes the plaintext
    assert not session.workspace.exists()

    assert session.read_file("attachments/keep.txt") == b"hold onto me"  # restored from the seal


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


async def test_seal_drops_symlinks_so_one_bad_link_cant_brick_restore(tmp_path):
    vault = await _vault(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    (work / "real.txt").write_text("keep me")
    (work / "evil").symlink_to("/etc/passwd")  # an absolute link the agent could plant

    sealed = _seal_workspace(work, _EXCLUDES, vault)
    restored = tmp_path / "restored"
    _restore_workspace(sealed, restored, vault)  # must NOT raise on the bad link

    assert (restored / "real.txt").read_text() == "keep me"  # the real file survives
    assert not (restored / "evil").exists()  # the symlink was never archived


async def test_reaper_defers_while_the_vault_is_locked(tmp_path):
    vault = Vault(tmp_path / "k.json")
    await vault.setup("pw")
    vault.lock()
    manager = _manager(tmp_path, vault, idle_ttl_s=0.0)
    session = await manager.acquire("conv-a")
    session.workspace.mkdir(parents=True, exist_ok=True)
    (session.workspace / "f.txt").write_text("data")

    await manager._sweep()  # cannot seal without the key → must not reap

    assert manager._sessions  # session kept, not evicted
    assert session.workspace.exists()  # not killed-and-stranded as plaintext
    assert not session.sealed.exists()


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


# --- image warm-up coordination: a cold create waits, not races (sandbox-01) --
def _pinned_backend() -> ContainerSandbox:
    return ContainerSandbox(runtime="docker")


async def test_ensure_up_waits_for_a_pending_image_warmup_before_creating(tmp_path, monkeypatch):
    vault = await _vault(tmp_path)
    warmup = ImageWarmup()
    warmup.start_pulling()  # simulate the background pull actually being in flight
    session = SandboxSession(
        "s1",
        workspace=tmp_path / "work",
        sealed=tmp_path / "sealed.tar.enc.gz",
        backend=_pinned_backend(),
        vault=vault,
        excludes=(),
        warmup=warmup,
    )

    created: list[list[str]] = []

    async def fake_run_subprocess(argv, **_kwargs):
        created.append(argv)
        return False, 0, b"", b""

    async def fake_kill_quietly(_runtime) -> None:
        return None

    monkeypatch.setattr(session_mod, "run_subprocess", fake_run_subprocess)
    monkeypatch.setattr(session, "_kill_quietly", fake_kill_quietly)

    task = asyncio.create_task(session._ensure_up())
    await asyncio.sleep(0.02)  # let it start and block on the still-pending pull
    assert not task.done()
    assert not created  # no container-create attempted while the pull is in flight

    warmup.mark_done(True)  # the background pull resolves
    await asyncio.wait_for(task, timeout=1.0)
    assert session.is_warm
    assert created  # now proceeds to the (fast, image-cached) create


async def test_ensure_up_needs_no_warmup_wire_up_at_all(tmp_path, monkeypatch):
    # A bare unit-constructed session (warmup=None, the default) skips the
    # coordination outright — existing callers that don't wire one keep working.
    vault = await _vault(tmp_path)
    session = SandboxSession(
        "s1",
        workspace=tmp_path / "work",
        sealed=tmp_path / "sealed.tar.enc.gz",
        backend=_pinned_backend(),
        vault=vault,
        excludes=(),
    )

    async def fake_run_subprocess(argv, **_kwargs):
        return False, 0, b"", b""

    monkeypatch.setattr(session_mod, "run_subprocess", fake_run_subprocess)
    monkeypatch.setattr(session, "_kill_quietly", lambda _r: _noop())

    await asyncio.wait_for(session._ensure_up(), timeout=1.0)
    assert session.is_warm


async def _noop() -> None:
    return None


async def test_ensure_up_gives_a_truthful_message_when_the_pull_never_resolves(
    tmp_path, monkeypatch
):
    vault = await _vault(tmp_path)
    warmup = ImageWarmup()
    warmup.start_pulling()  # in flight, and never marked done — simulates a stuck pull
    session = SandboxSession(
        "s1",
        workspace=tmp_path / "work",
        sealed=tmp_path / "sealed.tar.enc.gz",
        backend=_pinned_backend(),
        vault=vault,
        excludes=(),
        warmup=warmup,
    )
    monkeypatch.setattr(session_mod, "IMAGE_PULL_TIMEOUT_S", 0.05)

    with pytest.raises(SandboxError, match="still downloading"):
        await asyncio.wait_for(session._ensure_up(), timeout=1.0)


async def test_ensure_up_proceeds_when_the_pull_resolved_but_failed(tmp_path, monkeypatch):
    # The pull resolved (event set) but found nothing cached either — that's a
    # genuinely-unavailable image, not "still downloading"; let the ordinary
    # create attempt run and report its own real error (fail-closed, unchanged).
    vault = await _vault(tmp_path)
    warmup = ImageWarmup()
    warmup.mark_done(False)
    session = SandboxSession(
        "s1",
        workspace=tmp_path / "work",
        sealed=tmp_path / "sealed.tar.enc.gz",
        backend=_pinned_backend(),
        vault=vault,
        excludes=(),
        warmup=warmup,
    )

    async def fake_run_subprocess(argv, **_kwargs):
        return False, 1, b"", b"no such image"

    monkeypatch.setattr(session_mod, "run_subprocess", fake_run_subprocess)
    monkeypatch.setattr(session, "_kill_quietly", lambda _r: _noop())

    with pytest.raises(SandboxError, match="failed to start sandbox session"):
        await asyncio.wait_for(session._ensure_up(), timeout=1.0)


async def test_run_in_waits_for_a_pending_image_warmup_before_the_network_call(
    tmp_path, monkeypatch
):
    # The `spec.network=True` path bypasses `_ensure_up` entirely (it runs a
    # throwaway bridge container via `run_in` instead of exec-ing into the warm
    # session), so it needs its own wait-out-the-pull coordination — otherwise a
    # cold-boot network call can race its own implicit pull against a much shorter
    # exec timeout (sandbox-01, extended to the network branch).
    vault = await _vault(tmp_path)
    warmup = ImageWarmup()
    warmup.start_pulling()  # simulate the background pull actually being in flight
    session = SandboxSession(
        "s1",
        workspace=tmp_path / "work",
        sealed=tmp_path / "sealed.tar.enc.gz",
        backend=_pinned_backend(),
        vault=vault,
        excludes=(),
        warmup=warmup,
    )

    called: list[SandboxSpec] = []

    async def fake_run_in(_workspace, spec):
        called.append(spec)
        return SandboxResult(exit_code=0, stdout="ok", stderr="")

    monkeypatch.setattr(session._backend, "run_in", fake_run_in)

    spec = SandboxSpec(command=["true"], network=True)
    task = asyncio.create_task(session.run(spec))
    await asyncio.sleep(0.02)  # let it start and block on the still-pending pull
    assert not task.done()
    assert not called  # no network call attempted while the pull is in flight

    warmup.mark_done(True)  # the background pull resolves
    result = await asyncio.wait_for(task, timeout=1.0)
    assert result.exit_code == 0
    assert called  # now proceeds to the (fast, image-cached) network call


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


# --- the live-session cap: a ceiling in count, not only in time --------------
async def test_a_new_session_displaces_the_least_recently_used_one_at_the_cap(tmp_path):
    vault = await _vault(tmp_path)
    manager = _manager(tmp_path, vault, max_sessions=2)
    first = await manager.acquire("conv-a")
    second = await manager.acquire("conv-b")
    second.workspace.mkdir(parents=True, exist_ok=True)
    (second.workspace / "notes.txt").write_text("keep me")
    await asyncio.sleep(0.01)
    first.touch()  # conv-b is now the least recently used

    third = await manager.acquire("conv-c")

    assert set(manager._sessions) == {_safe_key("conv-a"), _safe_key("conv-c")}
    assert third is manager._sessions[_safe_key("conv-c")]
    # Displaced, not discarded: sealed exactly as an idle reap seals, and the files come
    # back the next time that conversation runs code.
    assert second.sealed.exists()
    assert not second.workspace.exists()
    revived = await manager.acquire("conv-b")
    revived._ensure_workspace()
    assert (revived.workspace / "notes.txt").read_text() == "keep me"


async def test_the_cap_never_displaces_a_session_with_a_call_in_flight(tmp_path):
    vault = await _vault(tmp_path)
    manager = _manager(tmp_path, vault, max_sessions=1)
    busy = await manager.acquire("conv-a")
    await busy._lock.acquire()  # simulate a call in flight
    try:
        await manager.acquire("conv-b")
        # Over the cap rather than failing the tool call the operator is watching; the
        # idle sweep collects the overflow once the work finishes.
        assert set(manager._sessions) == {_safe_key("conv-a"), _safe_key("conv-b")}
    finally:
        busy._lock.release()


async def test_the_cap_defers_while_the_vault_is_locked(tmp_path):
    vault = Vault(tmp_path / "k.json")
    await vault.setup("pw")
    manager = _manager(tmp_path, vault, max_sessions=1)
    first = await manager.acquire("conv-a")
    first.workspace.mkdir(parents=True, exist_ok=True)
    (first.workspace / "f.txt").write_text("data")
    vault.lock()

    await manager.acquire("conv-b")

    # Reaping seals, sealing needs the key — a container too many beats stranding the
    # agent's plaintext files on disk.
    assert set(manager._sessions) == {_safe_key("conv-a"), _safe_key("conv-b")}
    assert first.workspace.exists()
    assert not first.sealed.exists()


# --- a sweep's sealing must not stall unrelated conversations (sandbox-02) ---
async def test_sweep_does_not_block_acquire_for_an_unrelated_conversation(tmp_path, monkeypatch):
    vault = await _vault(tmp_path)
    manager = _manager(tmp_path, vault, idle_ttl_s=0.0)
    stale = await manager.acquire("conv-stale")
    stale.workspace.mkdir(parents=True, exist_ok=True)

    seal_started = asyncio.Event()
    release_seal = asyncio.Event()

    async def slow_shutdown(self) -> None:
        seal_started.set()
        await release_seal.wait()

    monkeypatch.setattr(SandboxSession, "shutdown", slow_shutdown)

    sweep_task = asyncio.create_task(manager._sweep())
    await asyncio.wait_for(seal_started.wait(), timeout=1.0)

    # A different conversation must proceed immediately — it must not wait on
    # the manager lock for the sum of every in-flight seal.
    other = await asyncio.wait_for(manager.acquire("conv-other"), timeout=1.0)
    assert other is not None

    release_seal.set()
    await asyncio.wait_for(sweep_task, timeout=1.0)


async def test_acquire_for_a_mid_seal_key_waits_for_its_own_teardown(tmp_path, monkeypatch):
    vault = await _vault(tmp_path)
    manager = _manager(tmp_path, vault, idle_ttl_s=0.0)
    original = await manager.acquire("conv-a")
    original.workspace.mkdir(parents=True, exist_ok=True)

    seal_started = asyncio.Event()
    release_seal = asyncio.Event()

    async def slow_shutdown(self) -> None:
        seal_started.set()
        await release_seal.wait()

    monkeypatch.setattr(SandboxSession, "shutdown", slow_shutdown)

    sweep_task = asyncio.create_task(manager._sweep())
    await asyncio.wait_for(seal_started.wait(), timeout=1.0)

    acquire_task = asyncio.create_task(manager.acquire("conv-a"))
    await asyncio.sleep(0.05)
    assert not acquire_task.done()  # same key mid-seal — must wait for it specifically

    release_seal.set()
    revived = await asyncio.wait_for(acquire_task, timeout=1.0)
    await asyncio.wait_for(sweep_task, timeout=1.0)
    assert revived is not original  # a fresh session, minted only once teardown finished
    assert not manager._tearing_down  # the tombstone is cleared afterward


async def test_purge_waits_for_an_in_flight_sweep_seal_on_the_same_key(tmp_path, monkeypatch):
    vault = await _vault(tmp_path)
    manager = _manager(tmp_path, vault, idle_ttl_s=0.0)
    session = await manager.acquire("conv-a")
    session.workspace.mkdir(parents=True, exist_ok=True)

    seal_started = asyncio.Event()
    release_seal = asyncio.Event()

    async def slow_shutdown(self) -> None:
        seal_started.set()
        await release_seal.wait()

    monkeypatch.setattr(SandboxSession, "shutdown", slow_shutdown)

    sweep_task = asyncio.create_task(manager._sweep())
    await asyncio.wait_for(seal_started.wait(), timeout=1.0)

    purge_task = asyncio.create_task(manager.purge("conv-a"))
    await asyncio.sleep(0.05)
    assert not purge_task.done()  # waits for the sweep's seal before deleting anything

    release_seal.set()
    await asyncio.wait_for(purge_task, timeout=1.0)
    await asyncio.wait_for(sweep_task, timeout=1.0)
    assert not manager._tearing_down


# --- purge: deleting a conversation removes its sandbox outright -------------
async def test_purge_drops_the_session_and_deletes_its_workspace(tmp_path):
    vault = await _vault(tmp_path)
    manager = _manager(tmp_path, vault)
    session = await manager.acquire("conv-a")
    session.workspace.mkdir(parents=True, exist_ok=True)
    (session.workspace / "f.txt").write_text("data")

    await manager.purge("conv-a")

    assert not manager._sessions  # evicted from the registry
    assert not session.workspace.exists()  # plaintext deleted, not sealed
    assert not session.sealed.exists()  # nothing preserved


async def test_purge_deletes_a_cold_sealed_archive_with_no_live_session(tmp_path):
    # A sealed-but-unloaded conversation: an archive on disk and no session object.
    vault = await _vault(tmp_path)
    manager = _manager(tmp_path, vault)
    safe = _safe_key("conv-cold")
    sealed = tmp_path / "sandbox" / "sealed" / f"{safe}.tar.enc.gz"
    sealed.parent.mkdir(parents=True, exist_ok=True)
    sealed.write_bytes(b"sealed-bytes")
    work = tmp_path / "sandbox" / "work" / safe
    work.mkdir(parents=True, exist_ok=True)
    (work / "leftover.txt").write_text("x")

    await manager.purge("conv-cold")  # nothing in the registry to stop

    assert not sealed.exists()
    assert not work.exists()


async def test_purge_is_safe_when_there_is_nothing_to_remove(tmp_path):
    vault = await _vault(tmp_path)
    manager = _manager(tmp_path, vault)
    await manager.purge("never-existed")  # must not raise
    assert not manager._sessions


# --- live-preview status: reap/purge leave a legible "stopped" signal --------
def _fake_preview(token: str) -> PreviewHandle:
    return PreviewHandle(
        token=token, container="c", host_port=1, container_port=2, command=("srv",)
    )


async def test_preview_status_is_unknown_for_a_token_never_seen(tmp_path):
    vault = await _vault(tmp_path)
    manager = _manager(tmp_path, vault)
    assert manager.preview_status("no-such-token") == "unknown"


async def test_preview_status_is_running_while_the_preview_is_live(tmp_path):
    vault = await _vault(tmp_path)
    manager = _manager(tmp_path, vault)
    session = await manager.acquire("conv-a")
    session._preview = _fake_preview("tok-1")
    manager._previews["tok-1"] = session.key

    assert manager.preview_status("tok-1") == "running"


async def test_idle_reap_marks_the_running_previews_token_stopped(tmp_path):
    # The failure this guards: an idle-reaped preview used to vanish with no signal
    # at all — `preview_status` now lets a client learn the head died, not just that
    # its URL 404s.
    vault = await _vault(tmp_path)
    manager = _manager(tmp_path, vault, idle_ttl_s=0.0)
    session = await manager.acquire("conv-a")
    session.workspace.mkdir(parents=True, exist_ok=True)
    session._preview = _fake_preview("tok-1")
    manager._previews["tok-1"] = session.key
    assert manager.preview_status("tok-1") == "running"

    await manager._sweep()

    assert not manager._sessions  # the session itself was reaped, as before
    assert manager.preview_status("tok-1") == "stopped"  # but the token now says why


async def test_purge_marks_the_running_previews_token_stopped(tmp_path):
    vault = await _vault(tmp_path)
    manager = _manager(tmp_path, vault)
    session = await manager.acquire("conv-a")
    session.workspace.mkdir(parents=True, exist_ok=True)
    session._preview = _fake_preview("tok-1")
    manager._previews["tok-1"] = session.key

    await manager.purge("conv-a")

    assert manager.preview_status("tok-1") == "stopped"


async def test_stopped_tokens_are_pruned_after_their_ttl(tmp_path, monkeypatch):
    vault = await _vault(tmp_path)
    manager = _manager(tmp_path, vault, idle_ttl_s=0.0)
    session = await manager.acquire("conv-a")
    session.workspace.mkdir(parents=True, exist_ok=True)
    session._preview = _fake_preview("tok-1")
    manager._previews["tok-1"] = session.key

    await manager._sweep()
    assert manager.preview_status("tok-1") == "stopped"

    # Fast-forward past the tombstone's TTL, then force a prune via another mark
    # (mirrors real usage — the map is pruned lazily on the next stop/reap/purge).
    frozen_future = time.monotonic() + manager._STOPPED_TOKEN_TTL_S + 1
    monkeypatch.setattr("time.monotonic", lambda: frozen_future)
    other = await manager.acquire("conv-b")
    other.workspace.mkdir(parents=True, exist_ok=True)
    other._preview = _fake_preview("tok-2")
    manager._previews["tok-2"] = other.key
    await manager.purge("conv-b")

    assert manager.preview_status("tok-1") == "unknown"  # aged out
    assert manager.preview_status("tok-2") == "stopped"  # freshly tombstoned


# --- the pre-warmed spare pool (sandbox-06) -----------------------------------
def _fake_container_create(monkeypatch, *, created: list[list[str]] | None = None):
    """Fake every `docker run --detach ...` as an instant success — no real
    runtime needed to exercise the spare pool's bookkeeping."""
    log = created if created is not None else []

    async def fake_run_subprocess(argv, **_kwargs):
        log.append(argv)
        return False, 0, b"", b""

    monkeypatch.setattr(session_mod, "run_subprocess", fake_run_subprocess)
    return log


async def test_replenish_only_proceeds_once_the_image_warmup_resolves_ready(tmp_path, monkeypatch):
    created = _fake_container_create(monkeypatch)
    vault = await _vault(tmp_path)
    manager = _manager(
        tmp_path, vault, backend=_pinned_backend(), spare_enabled=True, spare_count=1
    )
    manager._image_warmup.start_pulling()  # simulate the boot pull actually in flight

    manager._kick_replenish()
    await asyncio.sleep(0.02)
    assert not manager._spares  # the pull hasn't resolved yet — no spare created
    assert not created

    manager._image_warmup.mark_done(True)
    manager._kick_replenish()
    await asyncio.wait_for(manager._replenish_task, timeout=1.0)

    assert len(manager._spares) == 1
    spare = manager._spares[0]
    assert spare.workspace.exists()
    # Same hardening as an ordinary session's container.
    joined = " ".join(created[-1])
    assert "--network none" in joined
    assert "--cap-drop ALL" in joined
    assert "--read-only" in joined
    assert "--pids-limit" in joined


async def test_a_spare_is_containerised_exactly_like_a_session_not_merely_similarly(
    tmp_path, monkeypatch
):
    # The hardening flags *are* the sandbox: no network, dropped capabilities, a read-only
    # root, a pid cap, one bind mount. A spare that came up any softer than a session's own
    # container would be a hole with nothing watching it, so the two argv must differ in
    # nothing but the container name and the directory mounted — not merely agree on a
    # handful of flags a test remembered to list.
    vault = await _vault(tmp_path)
    created = _fake_container_create(monkeypatch)

    manager = _manager(
        tmp_path, vault, backend=_pinned_backend(), spare_enabled=True, spare_count=1
    )
    manager._image_warmup.mark_done(True)
    manager._kick_replenish()
    await asyncio.wait_for(manager._replenish_task, timeout=1.0)
    spare = manager._spares[0]
    spare_argv = created[-1]

    session = SandboxSession(
        "s1",
        workspace=tmp_path / "work",
        sealed=tmp_path / "sealed.tar.enc.gz",
        backend=_pinned_backend(),
        vault=vault,
        excludes=(),
        warmup=manager._image_warmup,
    )

    async def fake_kill_quietly(_runtime) -> None:
        return None

    monkeypatch.setattr(session, "_kill_quietly", fake_kill_quietly)
    await session._ensure_up()
    session_argv = created[-1]

    def normalised(argv: list[str], name: str, workspace) -> list[str]:
        return [arg.replace(name, "<name>").replace(str(workspace), "<workspace>") for arg in argv]

    assert normalised(spare_argv, spare.container, spare.workspace) == normalised(
        session_argv, session.container, session.workspace
    )


async def test_replenish_skips_silently_when_the_image_is_confirmed_unavailable(
    tmp_path, monkeypatch
):
    created = _fake_container_create(monkeypatch)
    vault = await _vault(tmp_path)
    manager = _manager(tmp_path, vault, backend=_pinned_backend(), spare_enabled=True)
    manager._image_warmup.mark_done(False)  # pull failed, nothing cached either

    manager._kick_replenish()
    await asyncio.wait_for(manager._replenish_task, timeout=1.0)

    assert not manager._spares
    assert not created  # never even attempted a create against a known-bad image


async def test_a_cold_acquire_claims_a_spare_and_kicks_a_background_replenish(
    tmp_path, monkeypatch
):
    _fake_container_create(monkeypatch)
    vault = await _vault(tmp_path)
    manager = _manager(
        tmp_path, vault, backend=_pinned_backend(), spare_enabled=True, spare_count=1
    )
    manager._image_warmup.mark_done(True)
    manager._kick_replenish()
    await asyncio.wait_for(manager._replenish_task, timeout=1.0)
    spare = manager._spares[0]

    session = await manager.acquire("conv-claim")

    assert session.is_warm  # adopted the spare's already-running container — no cold start
    assert session.container == spare.container
    # Adopted in place: the session keeps the spare's own dir — the path the
    # container's bind mount was established on. Renaming it under the live mount
    # breaks the mount on VM-backed runtimes (Docker Desktop on macOS).
    assert session.workspace == spare.workspace
    assert session.workspace.exists()
    assert not manager._spares  # claimed, not left dangling in the pool

    # Claiming kicks a background top-up so the pool returns to `spare_count`.
    await asyncio.wait_for(manager._replenish_task, timeout=1.0)
    assert len(manager._spares) == 1
    assert manager._spares[0] is not spare


async def test_a_stale_unclaimed_spare_is_reaped_by_the_idle_sweep_and_replenished(
    tmp_path, monkeypatch
):
    removed: list[str] = []

    async def fake_force_remove(_runtime, name: str) -> None:
        removed.append(name)

    _fake_container_create(monkeypatch)
    monkeypatch.setattr(session_mod, "force_remove_container", fake_force_remove)
    vault = await _vault(tmp_path)
    manager = _manager(tmp_path, vault, backend=_pinned_backend(), idle_ttl_s=0.0, spare_count=1)
    manager._image_warmup.mark_done(True)
    manager._kick_replenish()
    await asyncio.wait_for(manager._replenish_task, timeout=1.0)
    stale_workspace = manager._spares[0].workspace
    stale_container = manager._spares[0].container

    await manager._sweep()  # idle_ttl_s=0.0 ⇒ immediately stale, never claimed

    assert stale_container in removed  # its container was torn down
    assert not stale_workspace.exists()  # and its neutral workspace deleted
    await asyncio.wait_for(manager._replenish_task, timeout=1.0)
    assert len(manager._spares) == 1  # the pool topped itself back up
    assert manager._spares[0].workspace != stale_workspace


async def test_spare_disabled_never_creates_one(tmp_path, monkeypatch):
    created = _fake_container_create(monkeypatch)
    vault = await _vault(tmp_path)
    manager = _manager(tmp_path, vault, backend=_pinned_backend(), spare_enabled=False)
    manager._image_warmup.mark_done(True)

    manager._kick_replenish()  # a no-op — spares are disabled
    assert manager._replenish_task is None

    session = await manager.acquire("conv-x")  # falls back to the ordinary lazy path
    assert not session.is_warm
    assert not created


async def _pooled_manager(tmp_path, monkeypatch, **overrides) -> SandboxSessionManager:
    """A manager with one ready spare in the pool, no real runtime touched."""
    _fake_container_create(monkeypatch)
    vault = await _vault(tmp_path)
    manager = _manager(tmp_path, vault, backend=_pinned_backend(), spare_count=1, **overrides)
    manager._image_warmup.mark_done(True)
    manager._kick_replenish()
    await asyncio.wait_for(manager._replenish_task, timeout=1.0)
    return manager


async def test_a_spare_is_not_adopted_over_a_sealed_archive(tmp_path, monkeypatch):
    # An adopted spare keeps its own empty workspace, which would skip the sealed
    # restore — and the next reap would then seal that empty dir over the real
    # archive. A conversation with prior state must take the ordinary cold path.
    manager = await _pooled_manager(tmp_path, monkeypatch)
    safe = _safe_key("conv-history")
    sealed = tmp_path / "sandbox" / "sealed" / f"{safe}.tar.enc.gz"
    sealed.parent.mkdir(parents=True, exist_ok=True)
    sealed.write_bytes(b"sealed-bytes")

    session = await manager.acquire("conv-history")

    assert not session.is_warm  # ordinary lazy path — the restore stays in play
    assert session.workspace == manager._work_root / safe
    assert len(manager._spares) == 1  # the spare stays pooled for a cold key


async def test_a_spare_is_not_adopted_over_a_plaintext_workspace(tmp_path, monkeypatch):
    manager = await _pooled_manager(tmp_path, monkeypatch)
    safe = _safe_key("conv-files")
    work = tmp_path / "sandbox" / "work" / safe
    work.mkdir(parents=True, exist_ok=True)
    (work / "kept.txt").write_text("data")

    session = await manager.acquire("conv-files")

    assert not session.is_warm
    assert session.workspace == work
    assert (work / "kept.txt").exists()
    assert len(manager._spares) == 1


async def test_purge_deletes_an_adopted_spare_workspace(tmp_path, monkeypatch):
    # An adopted session's workspace is the spare's own dir, not the canonical
    # path — purge must delete the dir the session actually lives in.
    async def fake_force_remove(_runtime, name: str) -> None:
        return None

    monkeypatch.setattr(session_mod, "force_remove_container", fake_force_remove)
    manager = await _pooled_manager(tmp_path, monkeypatch)
    session = await manager.acquire("conv-adopted")
    assert session.is_warm
    (session.workspace / "made.txt").write_text("x")

    await manager.purge("conv-adopted")

    assert not manager._sessions
    assert not session.workspace.exists()


# --- exec runtime faults heal by container rebuild, not model flailing --------
_OCI_FAULT = (
    b"OCI runtime exec failed: exec failed: unable to start container process: "
    b"current working directory is outside of container mount namespace root "
    b"-- possible container breakout detected\r\n"
)


async def _healing_session(tmp_path, monkeypatch, exec_results):
    """A session whose fake runtime pops one canned (code, stdout) per exec and
    succeeds every container create; returns (session, calls, removed)."""
    calls: list[list[str]] = []
    removed: list[str] = []

    async def fake_run_subprocess(argv, **_kwargs):
        calls.append(argv)
        if argv[1] == "exec":
            code, out = exec_results.pop(0)
            return False, code, out, b""
        return False, 0, b"", b""

    async def fake_force_remove(_runtime, name: str) -> None:
        removed.append(name)

    monkeypatch.setattr(session_mod, "run_subprocess", fake_run_subprocess)
    monkeypatch.setattr(session_mod, "force_remove_container", fake_force_remove)
    vault = await _vault(tmp_path)
    manager = _manager(tmp_path, vault, backend=_pinned_backend(), spare_enabled=False)
    session = await manager.acquire("conv-heal")
    return session, calls, removed


async def test_exec_runtime_fault_rebuilds_the_container_and_retries(tmp_path, monkeypatch):
    # The failure this guards: a broken warm container (e.g. a stale workdir
    # mount) used to surface every exec as a "code failure" the model could only
    # flail at — now the container is rebuilt and the exec retried once.
    session, calls, removed = await _healing_session(
        tmp_path, monkeypatch, [(128, _OCI_FAULT), (0, b"healed")]
    )

    result = await session.run(SandboxSpec(command=["bash", "-c", "true"], timeout_s=5))

    assert result.ok
    assert result.stdout == "healed"
    # _ensure_up pre-clears the name once per create; the middle removal is the
    # heal tearing the broken container down.
    assert removed.count(session.container) == 3
    assert len([a for a in calls if a[1] == "run"]) == 2  # create + rebuild
    assert len([a for a in calls if a[1] == "exec"]) == 2  # fault + retry


async def test_exec_runtime_fault_twice_raises_a_legible_sandbox_error(tmp_path, monkeypatch):
    session, _calls, _removed = await _healing_session(
        tmp_path, monkeypatch, [(128, _OCI_FAULT), (128, _OCI_FAULT)]
    )

    with pytest.raises(SandboxError, match="container rebuild"):
        await session.run(SandboxSpec(command=["bash", "-c", "true"], timeout_s=5))


async def test_ordinary_code_failure_is_not_mistaken_for_a_runtime_fault(tmp_path, monkeypatch):
    session, calls, removed = await _healing_session(
        tmp_path, monkeypatch, [(1, b"NameError: x is not defined")]
    )

    result = await session.run(SandboxSpec(command=["python", "-c", "x"], timeout_s=5))

    assert not result.ok
    assert result.exit_code == 1
    # Only _ensure_up's one pre-create clear — no heal teardown, no rebuild: the
    # failure goes back to the model to fix.
    assert len(removed) == 1
    assert len([a for a in calls if a[1] == "run"]) == 1
    assert len([a for a in calls if a[1] == "exec"]) == 1


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
        read = await session.run(SandboxSpec(command=["bash", "-c", "cat note.txt"], timeout_s=60))
        assert "persisted" in read.stdout
    finally:
        await manager.stop()
