"""Per-conversation live sandboxes: selective sealing, lazy acquisition, the idle
reaper, and (with a runtime) file continuity across calls and across a reap."""

from __future__ import annotations

import asyncio
import shutil
import time
from pathlib import Path

import pytest

import services.sandbox.reconcile as reconcile_mod
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
    _partial_marker,
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


class _NoRuntime(ContainerSandbox):
    """A backend that resolves no container runtime, whatever the developer happens to
    have installed. The default for these tests, which exercise bookkeeping — sessions,
    seals, sweeps, boot reconciliation — and must never reach a real daemon: several of
    those paths issue `rm --force` / `network rm` by name, and a developer running the
    suite with the app live would otherwise have their own running sandbox removed
    from under them. A test that genuinely wants a runtime asks for one by name."""

    @property
    def runtime(self) -> str | None:
        return None


def _manager(tmp_path, vault, **overrides) -> SandboxSessionManager:
    backend = overrides.pop("backend", None) or _NoRuntime()
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

    called: list[tuple[SandboxSpec, str | None]] = []

    async def fake_run_in(_workspace, spec, *, name=None):
        called.append((spec, name))
        return SandboxResult(exit_code=0, stdout="ok", stderr="")

    cleared: list[str] = []

    async def fake_force_remove(_runtime, name, **_kwargs) -> None:
        cleared.append(name)

    monkeypatch.setattr(session._backend, "run_in", fake_run_in)
    monkeypatch.setattr(session_mod, "force_remove_container", fake_force_remove)

    spec = SandboxSpec(command=["true"], network=True)
    task = asyncio.create_task(session.run(spec))
    await asyncio.sleep(0.02)  # let it start and block on the still-pending pull
    assert not task.done()
    assert not called  # no network call attempted while the pull is in flight

    warmup.mark_done(True)  # the background pull resolves
    result = await asyncio.wait_for(task, timeout=1.0)
    assert result.exit_code == 0
    assert called  # now proceeds to the (fast, image-cached) network call
    # And the throwaway box is named, so a cancelled call's leftover is something
    # a later teardown and the next boot's reconciliation can both still find —
    # which in turn means the name has to be claimed before it can be used.
    assert called[0][1] == "odysseus-egress-s1"
    assert cleared == ["odysseus-egress-s1"]


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
    # `start()` reconciles first, and reconciliation removes containers by name — with
    # the runtime-less default backend it has nothing to talk to, which is the point.
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


class _Work:
    """A stand-in for the ``Run`` a session is claimed by — the sandbox only ever asks
    whether the work is over."""

    def __init__(self) -> None:
        self.is_terminal = False


async def test_the_cap_never_displaces_a_session_a_live_run_is_working_in(tmp_path):
    # The lock is held for one exec; a turn is a dozen of them with the model thinking in
    # between. Displacing in one of those gaps seals the workspace — and the seal drops
    # `node_modules`/`.venv`/`.git` by design, so the run's next tool call would come back
    # to a workspace missing exactly what it just spent minutes installing.
    vault = await _vault(tmp_path)
    manager = _manager(tmp_path, vault, max_sessions=1)
    turn = _Work()
    working = await manager.acquire("conv-a", holder=turn)
    (working.workspace / "node_modules").mkdir(parents=True, exist_ok=True)

    await manager.acquire("conv-b")  # thinking, not executing: the lock is free

    assert not working.is_busy  # the old signal says "reap me"
    assert set(manager._sessions) == {_safe_key("conv-a"), _safe_key("conv-b")}
    assert (working.workspace / "node_modules").exists()


async def test_the_claim_lasts_exactly_as_long_as_the_run_does(tmp_path):
    # And no longer: a claim released only by a hand-back would be leaked by every
    # cancelled turn, and the cap would decay into no cap at all.
    vault = await _vault(tmp_path)
    manager = _manager(tmp_path, vault, max_sessions=1)
    turn = _Work()
    working = await manager.acquire("conv-a", holder=turn)
    working.workspace.mkdir(parents=True, exist_ok=True)
    (working.workspace / "notes.txt").write_text("keep me")
    await manager.acquire("conv-b")

    turn.is_terminal = True  # stopped, failed or answered — the sandbox cannot tell

    assert working.is_displaceable
    await manager.acquire("conv-c")
    assert _safe_key("conv-a") not in manager._sessions
    assert working.sealed.exists()


async def test_the_cap_never_displaces_a_conversation_serving_a_live_preview(tmp_path):
    # Reaping drops the token the proxy resolves, so the page the operator is watching
    # turns into a 404 — with the server killed out from under an iframe that has no
    # reason to expect it. The idle sweep may still collect a preview nobody has loaded
    # in half an hour; that is the difference between a deadline and a ceiling.
    vault = await _vault(tmp_path)
    manager = _manager(tmp_path, vault, max_sessions=1)
    serving = await manager.acquire("conv-a")
    serving._preview = _fake_preview("tok-live")
    manager._previews["tok-live"] = serving.key

    await manager.acquire("conv-b")

    assert set(manager._sessions) == {_safe_key("conv-a"), _safe_key("conv-b")}
    assert manager.preview_status("tok-live") == "running"


# --- an evicted session's seal belongs to the manager, not to whoever triggered it ---
async def test_a_cancelled_acquire_does_not_abort_another_conversations_seal(tmp_path):
    """Stop is the operator's most-used control, and at the cap the acquiring run is
    sealing somebody *else's* conversation. Cancelled mid-seal, the archive is never
    written, the plaintext workspace stays on disk, and the container is left out of
    every map — no sweep can find it and no purge names it."""
    vault = await _vault(tmp_path)
    manager = _manager(tmp_path, vault, max_sessions=1)
    displaced = await manager.acquire("conv-a")
    displaced.workspace.mkdir(parents=True, exist_ok=True)
    (displaced.workspace / "notes.txt").write_text("keep me")

    sealing, resume = asyncio.Event(), asyncio.Event()
    real_shutdown = displaced.shutdown

    async def slow_shutdown() -> None:
        sealing.set()
        await resume.wait()
        await real_shutdown()

    displaced.shutdown = slow_shutdown  # type: ignore[method-assign]

    acquiring = asyncio.create_task(manager.acquire("conv-b"))
    await asyncio.wait_for(sealing.wait(), timeout=2.0)
    in_flight = list(manager._teardowns)
    acquiring.cancel()
    with pytest.raises(asyncio.CancelledError):
        await acquiring

    resume.set()
    await asyncio.gather(*in_flight)

    assert displaced.sealed.exists()  # the seal finished on the manager's own task
    assert not displaced.workspace.exists()  # no plaintext left behind
    assert set(manager._sessions) == {_safe_key("conv-b")}


async def test_a_failed_seal_leaves_the_session_live_for_the_sweeper(tmp_path):
    # A session dropped from the map on a failed teardown is a container nothing will
    # ever reap and a workspace nothing will ever seal. Put it back and let the idle
    # sweep try again.
    vault = await _vault(tmp_path)
    manager = _manager(tmp_path, vault, max_sessions=1)
    displaced = await manager.acquire("conv-a")

    async def failing_shutdown() -> None:
        raise RuntimeError("the archive could not be written")

    displaced.shutdown = failing_shutdown  # type: ignore[method-assign]

    await manager.acquire("conv-b")

    assert manager._sessions[_safe_key("conv-a")] is displaced
    assert not manager._tearing_down  # and not wedged behind a tombstone either
    assert await manager.acquire("conv-a") is displaced


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


# --- boot reconciliation + sealing what an unclean shutdown left --------------
def _fake_runtime_calls(monkeypatch, replies: dict[str, tuple[int, bytes]] | None = None):
    """Record every runtime argv and answer canned output per subcommand — the
    listings reconciliation reads, with no real runtime anywhere near it."""
    calls: list[list[str]] = []
    answers = replies or {}

    async def fake_run_subprocess(argv, **_kwargs):
        calls.append(list(argv))
        code, out = answers.get(" ".join(argv[1:3]), (0, b""))
        return False, code, out, b""

    monkeypatch.setattr(reconcile_mod, "run_subprocess", fake_run_subprocess)
    monkeypatch.setattr(session_mod, "run_subprocess", fake_run_subprocess)
    return calls


async def test_reconcile_removes_stale_named_containers_and_networks(tmp_path, monkeypatch):
    # What a crash leaves behind is invisible to every map the manager keeps: a
    # container nothing will exec into, a network nothing joins, and the scratch dirs
    # of a pool this build no longer runs. Boot is the one moment clearing them
    # wholesale is safe, so this is where it has to happen.
    removed: list[str] = []

    async def fake_force_remove(_runtime, name: str, **_kwargs) -> None:
        removed.append(name)

    calls = _fake_runtime_calls(
        monkeypatch,
        {
            "ps -a": (0, b"odysseus-sbx-sconv-a\nodysseus-pre-sconv-a\nodysseus-egress-sconv-b\n"),
            "network ls": (0, b"odysseus-net-sconv-a\n"),
        },
    )
    monkeypatch.setattr(reconcile_mod, "force_remove_container", fake_force_remove)
    vault = await _vault(tmp_path)
    manager = _manager(tmp_path, vault, backend=_pinned_backend())
    leftover_pool_dir = manager._work_root / "_spare-1-abcd"
    leftover_pool_dir.mkdir(parents=True)
    kept = manager._work_root / _safe_key("conv-real")
    kept.mkdir(parents=True)

    await manager.reconcile()

    # The listings are anchored to our own names — an unanchored filter would sweep
    # up a container the operator merely named after the project.
    listing = [c for c in calls if c[1] in ("ps", "network")]
    assert listing[0] == [
        "docker", "ps", "-a", "--filter", "name=^odysseus-(sbx|pre|egress)-",
        "--format", "{{.Names}}",
    ]
    assert listing[1] == [
        "docker", "network", "ls", "--filter", "name=^odysseus-net-", "--format", "{{.Name}}",
    ]
    assert removed == [
        "odysseus-sbx-sconv-a",
        "odysseus-pre-sconv-a",
        "odysseus-egress-sconv-b",
    ]
    assert ["docker", "network", "rm", "odysseus-net-sconv-a"] in calls
    assert not leftover_pool_dir.exists()
    assert kept.exists()  # a conversation's own workspace is not pool scratch


async def test_reconcile_survives_a_runtime_that_cannot_answer(tmp_path, monkeypatch):
    # A daemon that is down at boot is a reason to skip reconciliation, never to
    # stop the app from starting.
    _fake_runtime_calls(monkeypatch, {"ps -a": (1, b""), "network ls": (1, b"")})
    vault = await _vault(tmp_path)
    manager = _manager(tmp_path, vault, backend=_pinned_backend())

    await manager.reconcile()  # must not raise


async def test_sweep_seals_a_plaintext_workspace_with_no_session(tmp_path):
    # The residue of a process that died before its seal ran: files in the clear that
    # no session owns. Left alone they quietly break the vault's at-rest promise, so
    # the sweep adopts and seals them.
    vault = await _vault(tmp_path)
    manager = _manager(tmp_path, vault)
    safe = _safe_key("conv-orphan")
    orphan = manager._work_root / safe
    orphan.mkdir(parents=True)
    (orphan / "notes.txt").write_text("plaintext the last process never sealed")

    await manager._sweep()

    sealed = manager._sealed_root / f"{safe}.tar.enc.gz"
    assert sealed.exists()  # archived under the vault
    assert not orphan.exists()  # and the plaintext is gone
    assert not manager._sessions  # sealing an orphan does not revive it as a session
    assert not manager._tearing_down  # the tombstone it went through is released


async def test_sweep_leaves_an_orphan_workspace_alone_while_the_vault_is_locked(tmp_path):
    # Without the key there is nothing to seal *into*, and deleting the plaintext
    # would destroy the agent's files. Waiting is the only honest answer.
    vault = await _vault(tmp_path)
    manager = _manager(tmp_path, vault)
    orphan = manager._work_root / _safe_key("conv-orphan")
    orphan.mkdir(parents=True)
    (orphan / "notes.txt").write_text("data")
    vault.lock()

    await manager._sweep()

    assert (orphan / "notes.txt").exists()


async def test_sweep_adopts_stranded_workspaces_a_slice_at_a_time(tmp_path):
    # Every key in a batch is tombstoned for the whole batch, and an `acquire()` that
    # lands on a tombstone waits with nothing to show the operator. A crash with a
    # hundred live conversations must not turn into a hundred-seal wait for whoever
    # opens the last one, so a sweep takes a slice and the next sweep takes the rest.
    vault = await _vault(tmp_path)
    manager = _manager(tmp_path, vault)
    keys = [_safe_key(f"conv-{i}") for i in range(session_mod._ORPHAN_SEALS_PER_SWEEP + 2)]
    for safe in keys:
        (manager._work_root / safe).mkdir(parents=True)
        (manager._work_root / safe / "notes.txt").write_text("plaintext")

    await manager._sweep()
    sealed_first = [k for k in keys if (manager._sealed_root / f"{k}.tar.enc.gz").exists()]
    assert len(sealed_first) == session_mod._ORPHAN_SEALS_PER_SWEEP
    assert not manager._tearing_down  # and every tombstone in the slice is released

    await manager._sweep()

    assert all((manager._sealed_root / f"{k}.tar.enc.gz").exists() for k in keys)
    assert not any((manager._work_root / k).exists() for k in keys)


async def test_sealing_a_stranded_workspace_first_drops_the_containers_holding_it(
    tmp_path, monkeypatch
):
    # The dead process's containers can still be alive with this very directory mounted
    # at /work — boot reconciliation is skipped whenever the runtime was not up yet.
    # Sealing under a live mount archives a torn state and sends its later writes to a
    # deleted inode, so every mount comes off before the archive goes on — the egress
    # box included, which is the one a cancelled network call leaves behind.
    removed: list[tuple[str, bool]] = []
    safe = _safe_key("conv-orphan")

    async def fake_force_remove(_runtime, name: str, **_kwargs) -> None:
        removed.append((name, sealed.exists()))

    _fake_runtime_calls(monkeypatch)
    monkeypatch.setattr(session_mod, "force_remove_container", fake_force_remove)
    vault = await _vault(tmp_path)
    manager = _manager(tmp_path, vault, backend=_pinned_backend())
    sealed = manager._sealed_root / f"{safe}.tar.enc.gz"
    orphan = manager._work_root / safe
    orphan.mkdir(parents=True)
    (orphan / "notes.txt").write_text("plaintext the last process never sealed")

    await manager._sweep()

    assert removed == [
        (f"odysseus-sbx-{safe}", False),
        (f"odysseus-pre-{safe}", False),
        (f"odysseus-egress-{safe}", False),
    ]
    assert sealed.exists()


async def test_dropping_the_mounts_is_bounded_so_the_seal_still_happens(tmp_path, monkeypatch):
    # A whole batch of orphans is tombstoned while their mounts come off, and every
    # `acquire()` for those conversations waits behind it with nothing to show the
    # operator. So a daemon that has stopped answering costs a bounded pause and then
    # the seal goes ahead — the removals it did not manage are the next boot's problem.
    removed: list[str] = []

    async def fake_force_remove(_runtime, name: str, **_kwargs) -> None:
        removed.append(name)

    _fake_runtime_calls(monkeypatch)
    monkeypatch.setattr(session_mod, "force_remove_container", fake_force_remove)
    monkeypatch.setattr(session_mod, "_MOUNT_RELEASE_BUDGET_S", 0.0)
    vault = await _vault(tmp_path)
    manager = _manager(tmp_path, vault, backend=_pinned_backend())
    safe = _safe_key("conv-orphan")
    orphan = manager._work_root / safe
    orphan.mkdir(parents=True)
    (orphan / "notes.txt").write_text("plaintext the last process never sealed")

    await manager._sweep()

    assert removed == []  # not even one call is worth making with no budget left
    assert (manager._sealed_root / f"{safe}.tar.enc.gz").exists()
    assert not manager._tearing_down


async def test_a_stranded_workspace_releases_its_tombstone_even_if_the_mounts_will_not_drop(
    tmp_path, monkeypatch
):
    # The tombstones for a whole batch of orphans go down before any of them is sealed,
    # and only the teardown releases them. A removal that raises — or a reaper cancelled
    # mid-eviction — must not leave one set forever: `acquire()` for that conversation
    # waits on it with no timeout and nothing to show the operator.
    async def fake_force_remove(_runtime, _name: str, **_kwargs) -> None:
        raise RuntimeError("the daemon is having a bad day")

    _fake_runtime_calls(monkeypatch)
    monkeypatch.setattr(session_mod, "force_remove_container", fake_force_remove)
    vault = await _vault(tmp_path)
    manager = _manager(tmp_path, vault, backend=_pinned_backend())
    safe = _safe_key("conv-orphan")
    orphan = manager._work_root / safe
    orphan.mkdir(parents=True)
    (orphan / "notes.txt").write_text("plaintext the last process never sealed")

    await manager._sweep()

    assert not manager._tearing_down  # released, so the next acquire is not stuck
    assert await asyncio.wait_for(manager.acquire("conv-orphan"), timeout=1.0)


async def test_reconcile_stops_when_its_boot_budget_is_spent(tmp_path, monkeypatch):
    # Boot waits on this pass, and a daemon that accepts the connection without ever
    # answering would otherwise park startup there — per-container timeouts alone still
    # let a hundred leftovers add up. What the budget cuts short the next boot finishes.
    removed: list[str] = []

    async def fake_force_remove(_runtime, name: str, **_kwargs) -> None:
        removed.append(name)

    calls = _fake_runtime_calls(
        monkeypatch,
        {"ps -a": (0, b"odysseus-sbx-sconv-a\n"), "network ls": (0, b"odysseus-net-sconv-a\n")},
    )
    monkeypatch.setattr(reconcile_mod, "force_remove_container", fake_force_remove)
    monkeypatch.setattr(reconcile_mod, "_BUDGET_S", 0.0)
    vault = await _vault(tmp_path)
    manager = _manager(tmp_path, vault, backend=_pinned_backend())

    await manager.reconcile()

    assert calls == []  # not even the listing is worth a call with no budget left
    assert removed == []


def _archive_of(manager, vault, safe: str, files: dict[str, str]):
    """Seal ``files`` as ``safe``'s archive and return its path — the complete copy a
    half-finished workspace must never be allowed to overwrite."""
    source = manager._work_root / f"_source-{safe}"
    source.mkdir(parents=True)
    for name, text in files.items():
        (source / name).write_text(text)
    sealed = manager._sealed_root / f"{safe}.tar.enc.gz"
    sealed.parent.mkdir(parents=True, exist_ok=True)
    sealed.write_bytes(_seal_workspace(source, _EXCLUDES, vault))
    shutil.rmtree(source)
    return sealed


def _restored(sealed, vault, dest) -> set[str]:
    _restore_workspace(sealed.read_bytes(), dest, vault)
    return {p.name for p in dest.iterdir()}


async def test_a_fragment_of_a_restore_never_overwrites_the_archive_it_came_from(tmp_path):
    # Killed mid-extract, the workspace holds part of what the archive holds. To the
    # sweep it looks exactly like an unsealed orphan, and sealing it back would drop
    # every file the extract had not reached yet — irrecoverably. The marker is what
    # tells the two apart.
    vault = await _vault(tmp_path)
    manager = _manager(tmp_path, vault)
    safe = _safe_key("conv-frag")
    sealed = _archive_of(manager, vault, safe, {"a.txt": "first", "b.txt": "second"})
    workspace = manager._work_root / safe
    workspace.mkdir(parents=True)
    (workspace / "a.txt").write_text("first")
    _partial_marker(workspace).touch()

    await manager._sweep()

    assert _restored(sealed, vault, tmp_path / "check") == {"a.txt", "b.txt"}
    assert not workspace.exists()  # the fragment is still cleared from disk
    assert not _partial_marker(workspace).exists()


async def test_a_workspace_the_agent_emptied_seals_as_empty(tmp_path):
    # The mirror of the case above, and the reason "looks empty" can never be the test
    # for a fragment: the operator asked for the file to go, so all that is left is the
    # scratch dirs the seal drops anyway. Keeping the old archive here would hand the
    # deleted file straight back on the next restore.
    vault = await _vault(tmp_path)
    manager = _manager(tmp_path, vault)
    safe = _safe_key("conv-emptied")
    sealed = _archive_of(manager, vault, safe, {"report.md": "delete me"})
    workspace = manager._work_root / safe
    (workspace / ".home").mkdir(parents=True)
    (workspace / ".tmp").mkdir()

    await manager._sweep()

    assert _restored(sealed, vault, tmp_path / "check") == set()  # the deletion stuck
    assert not workspace.exists()


async def test_a_marked_fragment_is_thrown_away_and_restored_from_the_archive(tmp_path):
    # The same fragment reached from the other direction: the conversation comes back
    # before the sweep does. It must get its whole workspace, not the half on disk.
    vault = await _vault(tmp_path)
    manager = _manager(tmp_path, vault)
    safe = _safe_key("conv-frag")
    _archive_of(manager, vault, safe, {"a.txt": "first", "b.txt": "second"})
    workspace = manager._work_root / safe
    workspace.mkdir(parents=True)
    (workspace / "a.txt").write_text("half-written")
    _partial_marker(workspace).touch()

    session = await manager.acquire("conv-frag")

    assert session.read_file("a.txt") == b"first"
    assert session.read_file("b.txt") == b"second"
    assert not _partial_marker(workspace).exists()


async def test_a_restore_marks_the_fragment_before_it_creates_anything(tmp_path, monkeypatch):
    # Restoring is several steps and the process can die between any two of them. Dying
    # with the directory created and the marker not yet written leaves an empty, unmarked
    # workspace beside a complete archive — the one shape the orphan sweep adopts and
    # seals straight back over that archive. So the marker goes down first.
    vault = await _vault(tmp_path)
    manager = _manager(tmp_path, vault)
    safe = _safe_key("conv-crash")
    sealed = _archive_of(manager, vault, safe, {"a.txt": "first"})
    workspace = manager._work_root / safe
    real_mkdir = Path.mkdir

    def die_creating_the_workspace(self, *args, **kwargs):
        if self == workspace:
            raise OSError("the process died right here")
        return real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", die_creating_the_workspace)

    with pytest.raises(SandboxError):
        _restore_workspace(sealed.read_bytes(), workspace, vault)

    assert _partial_marker(workspace).exists()


async def test_a_file_write_racing_a_seal_waits_it_out_instead_of_tearing_the_workspace(
    tmp_path, monkeypatch
):
    # The file tools take no session lock — that is what keeps browsing and editing off
    # the container's critical path — so a run parked on an approval can be reaped and
    # sealed while it still holds this very session object, and its next write arrives
    # mid-archive. Interleaved, the two leave a torn directory with no marker on it,
    # which the orphan sweep then seals over the good archive.
    vault = await _vault(tmp_path)
    manager = _manager(tmp_path, vault)
    session = await manager.acquire("conv-race")
    session.ensure_workspace()
    (session.workspace / "notes.txt").write_text("what the seal captures")
    real_seal = session_mod._seal_workspace

    def slow_seal(workspace, excludes, vault):
        time.sleep(0.2)  # a real tar+gzip+AEAD is seconds; this is the same window
        return real_seal(workspace, excludes, vault)

    monkeypatch.setattr(session_mod, "_seal_workspace", slow_seal)

    sealing = asyncio.create_task(session.shutdown())
    await asyncio.sleep(0.05)  # let the seal thread get well inside the archive
    await asyncio.gather(sealing, asyncio.to_thread(session.write_file, "late.txt", b"x"))

    # The write landed on a workspace restored from the finished archive, so both files
    # are there and nothing is half-removed.
    assert (session.workspace / "notes.txt").read_text() == "what the seal captures"
    assert (session.workspace / "late.txt").read_bytes() == b"x"
    assert not _partial_marker(session.workspace).exists()


async def test_sweep_does_not_touch_a_workspace_its_own_session_still_holds(tmp_path):
    vault = await _vault(tmp_path)
    manager = _manager(tmp_path, vault, idle_ttl_s=3600.0)
    session = await manager.acquire("conv-live")
    session.ensure_workspace()
    (session.workspace / "wip.txt").write_text("still working")

    await manager._sweep()

    assert (session.workspace / "wip.txt").exists()
    assert manager.existing("conv-live") is session


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

    async def fake_force_remove(_runtime, name: str, **_kwargs) -> None:
        removed.append(name)

    monkeypatch.setattr(session_mod, "run_subprocess", fake_run_subprocess)
    monkeypatch.setattr(session_mod, "force_remove_container", fake_force_remove)
    vault = await _vault(tmp_path)
    manager = _manager(tmp_path, vault, backend=_pinned_backend())
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
    # The one test here that wants the developer's actual runtime rather than the
    # runtime-less default.
    manager = _manager(tmp_path, vault, backend=ContainerSandbox())
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
