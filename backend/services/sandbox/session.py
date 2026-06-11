"""Live per-conversation sandboxes — the warm-container model.

A conversation gets one container, **lazily** created the first time the agent
runs code in it and kept alive so it can iterate: fix an error, re-run, reuse a
dependency it just installed — all against the same live process and filesystem,
without rebuilding. An idle session is **reaped** to free resources after a TTL.

Continuity survives a reap because the agent's files do. The workspace is a
host-side directory bind-mounted into the container; on reap we **seal** it (the
agent's own files and any output it produced — virtual environments and language
caches are dropped, being cheaper to rebuild than to store) with the vault and
remove the plaintext, then restore it the next time the conversation runs code.
So files persist encrypted-at-rest across reaps; only the container's live
process/system state is rebuilt.

Two execution paths keep egress off by default without a fragile live-network
toggle: ordinary calls ``exec`` into the no-network session container; a call
that asks for the network runs as a one-shot ``--network bridge`` container over
the *same* workspace, so a fetched package lands in files the session then sees.
"""

from __future__ import annotations

import asyncio
import io
import re
import secrets
import shutil
import tarfile
import time
from collections.abc import Iterable
from fnmatch import fnmatch
from pathlib import Path

from core.vault import Vault

from .base import SandboxError, SandboxResult, SandboxSpec
from .container import (
    _BACKSTOP_GRACE_S,
    ContainerSandbox,
    detached_run_argv,
    force_remove_container,
    hardened_flags,
    run_subprocess,
    with_in_container_timeout,
)
from .preview import PreviewHandle, launch_preview, stop_preview_container

_SAFE = re.compile(r"[^A-Za-z0-9_.-]")


def _safe_key(key: str) -> str:
    """A container/dir-safe token for a conversation id (leading char guaranteed)."""
    return "s" + _SAFE.sub("-", key)


def _excluded(arcname: str, excludes: Iterable[str]) -> bool:
    parts = Path(arcname).parts
    return any(fnmatch(part, pat) for part in parts for pat in excludes)


def _seal_workspace(workspace: Path, excludes: Iterable[str], vault: Vault) -> bytes:
    """A gzip tar of the workspace, minus the excluded bloat, sealed by the vault.

    Only regular files and directories are archived. Symlinks/hardlinks/devices —
    which the agent (root in the box) can create — are dropped: an unsafe link
    would otherwise make the whole archive un-restorable under the ``data`` filter,
    losing every file with it."""

    def keep(ti: tarfile.TarInfo) -> tarfile.TarInfo | None:
        if _excluded(ti.name, excludes) or not (ti.isfile() or ti.isdir()):
            return None
        return ti

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for item in sorted(workspace.iterdir()):
            if _excluded(item.name, excludes):
                continue
            tar.add(item, arcname=item.name, filter=keep)
    return vault.encrypt_bytes(buf.getvalue())


def _restore_workspace(blob: bytes, workspace: Path, vault: Vault) -> None:
    try:
        raw = vault.decrypt_bytes(blob)
        workspace.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
            tar.extractall(workspace, filter="data")  # 'data' guards path traversal
    except Exception as exc:  # noqa: BLE001 — a damaged seal is a legible failure, not a crash
        raise SandboxError(f"could not restore the sandbox workspace: {exc}") from exc


class SandboxSession:
    """One conversation's live container plus its persistent workspace."""

    def __init__(
        self,
        key: str,
        *,
        workspace: Path,
        sealed: Path,
        backend: ContainerSandbox,
        vault: Vault,
        excludes: Iterable[str],
    ) -> None:
        self.key = key
        self.workspace = workspace
        self.sealed = sealed
        self.container = f"odysseus-sbx-{key}"
        self._preview_container = f"odysseus-pre-{key}"
        self._backend = backend
        self._vault = vault
        self._excludes = tuple(excludes)
        self._runtime: str | None = None
        self._running = False
        self._preview: PreviewHandle | None = None
        self._last_used = time.monotonic()
        self._lock = asyncio.Lock()

    @property
    def is_busy(self) -> bool:
        return self._lock.locked()

    @property
    def preview(self) -> PreviewHandle | None:
        return self._preview

    def touch(self) -> None:
        self._last_used = time.monotonic()

    def idle_seconds(self, now: float) -> float:
        return now - self._last_used

    async def run(self, spec: SandboxSpec) -> SandboxResult:
        async with self._lock:
            self.touch()
            try:
                return await self._run_inner(spec)
            except SandboxError:
                raise
            except Exception as exc:  # noqa: BLE001 — surface as a failure, never crash the agent
                raise SandboxError(f"unexpected sandbox failure: {exc}") from exc

    async def _run_inner(self, spec: SandboxSpec) -> SandboxResult:
        self._ensure_workspace()
        if spec.network:
            # Egress is granted per-call via a throwaway bridge container over
            # the same workspace, so the live session itself stays no-network.
            return await self._backend.run_in(self.workspace, spec)
        await self._ensure_up()
        backstop_timed_out, code, out, err = await run_subprocess(
            self._exec_argv(spec),
            stdin=spec.stdin,
            timeout_s=spec.timeout_s + _BACKSTOP_GRACE_S,
        )
        return SandboxResult(
            exit_code=code,
            stdout=out.decode("utf-8", "replace"),
            stderr=err.decode("utf-8", "replace"),
            # The in-container `timeout` exits 124 on overrun and actually kills
            # the process; the backstop only catches a hung exec client.
            timed_out=backstop_timed_out or code == 124,
        )

    def read_file(self, relpath: str) -> bytes:
        """Read a file the agent produced in this session's workspace, restoring
        from the sealed copy if the session was reaped. Guards against escape."""
        self._ensure_workspace()
        target = (self.workspace / relpath).resolve()
        if not target.is_relative_to(self.workspace.resolve()):
            raise SandboxError(f"path escapes the sandbox workspace: {relpath!r}")
        if not target.is_file():
            raise SandboxError(f"no such file in the sandbox: {relpath!r}")
        return target.read_bytes()

    async def start_preview(
        self, command: list[str], port: int, *, token: str, startup_timeout_s: float
    ) -> PreviewHandle:
        """Run ``command`` as a live server over this workspace, reachable on a
        loopback host port. Replaces any preview already running here (one per
        conversation). Raises :class:`SandboxError` if the server never binds."""
        async with self._lock:
            self.touch()
            self._ensure_workspace()
            runtime = self._backend.runtime
            if runtime is None:  # disappeared since detection — fail closed
                raise SandboxError("no container runtime available")
            await self._stop_preview_locked()
            handle = await launch_preview(
                runtime=runtime,
                backend=self._backend,
                workspace=self.workspace,
                container=self._preview_container,
                token=token,
                command=command,
                port=port,
                startup_timeout_s=startup_timeout_s,
            )
            self._runtime = runtime
            self._preview = handle
            return handle

    async def stop_preview(self) -> None:
        """Tear down this session's preview server, if any."""
        async with self._lock:
            await self._stop_preview_locked()

    async def _stop_preview_locked(self) -> None:
        if self._preview is None:
            return
        runtime = self._runtime or self._backend.runtime
        if runtime is not None:
            await stop_preview_container(runtime, self._preview.container)
        self._preview = None

    async def shutdown(self) -> None:
        """Kill the container and seal the workspace (when the vault is unlocked)."""
        async with self._lock:
            # Tear the preview's container down first — it holds the workspace mount
            # the seal is about to archive.
            await self._stop_preview_locked()
            if self._running:
                await self._kill()
                self._running = False
            if self.workspace.exists() and self._vault.is_unlocked:
                # Off-thread: tar+gzip+AEAD of a workspace must not block the loop.
                await asyncio.to_thread(self._seal_and_clear)
            # Vault locked ⇒ leave the plaintext workspace; the manager defers
            # reaping while locked, so a later (unlocked) reap seals it.

    def _seal_and_clear(self) -> None:
        self.sealed.parent.mkdir(parents=True, exist_ok=True)
        self.sealed.write_bytes(_seal_workspace(self.workspace, self._excludes, self._vault))
        shutil.rmtree(self.workspace, ignore_errors=True)

    def _ensure_workspace(self) -> None:
        if self.workspace.exists():
            return
        if self.sealed.exists():
            if not self._vault.is_unlocked:
                raise SandboxError("cannot restore the sandbox workspace: vault is locked")
            _restore_workspace(self.sealed.read_bytes(), self.workspace, self._vault)
        else:
            self.workspace.mkdir(parents=True, exist_ok=True)

    async def _ensure_up(self) -> None:
        if self._running:
            return
        runtime = self._backend.runtime
        if runtime is None:  # disappeared since detection — fail closed
            raise SandboxError("no container runtime available")
        await self._kill_quietly(runtime)  # clear any stale same-named container
        argv = detached_run_argv(
            runtime,
            self.container,
            hardened_flags(
                network=False,
                memory=self._backend.memory,
                cpus=self._backend.cpus,
                pids_limit=self._backend.pids_limit,
                workdir=self._backend.workdir,
                mount=self.workspace,
                env={},
            ),
            self._backend.image,
            ["sleep", "infinity"],  # keep the container alive between exec calls
        )
        _timed_out, code, _out, err = await run_subprocess(argv, timeout_s=60.0)
        if code != 0:
            raise SandboxError(f"failed to start sandbox session: {err.decode('utf-8', 'replace')}")
        self._runtime = runtime
        self._running = True

    def _exec_argv(self, spec: SandboxSpec) -> list[str]:
        argv = [self._runtime, "exec", "--interactive", "--workdir", self._backend.workdir]
        for key, value in spec.env.items():
            argv += ["--env", f"{key}={value}"]
        argv.append(self.container)
        argv += with_in_container_timeout(list(spec.command), spec.timeout_s)
        return argv  # type: ignore[return-value]  # _runtime set by _ensure_up

    async def _kill(self) -> None:
        if self._runtime is not None:
            await self._kill_quietly(self._runtime)

    async def _kill_quietly(self, runtime: str) -> None:
        await force_remove_container(runtime, self.container)


class SandboxSessionManager:
    """Maps a conversation to its live :class:`SandboxSession`, reaping idle ones.

    Built only when a container runtime is present (fail-closed detection lives in
    ``detect``), so its existence means code execution is available."""

    def __init__(
        self,
        backend: ContainerSandbox,
        vault: Vault,
        *,
        data_dir: Path,
        idle_ttl_s: float,
        reap_interval_s: float,
        excludes: Iterable[str],
        preview_startup_timeout_s: float = 20.0,
    ) -> None:
        self._backend = backend
        self._vault = vault
        self._work_root = data_dir / "sandbox" / "work"
        self._sealed_root = data_dir / "sandbox" / "sealed"
        self._idle_ttl = idle_ttl_s
        self._reap_interval = reap_interval_s
        self._excludes = tuple(excludes)
        self._preview_startup_timeout_s = preview_startup_timeout_s
        self._sessions: dict[str, SandboxSession] = {}
        # token → safe session key, so the proxy route resolves a preview in O(1).
        self._previews: dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._reaper: asyncio.Task | None = None

    async def acquire(self, key: str) -> SandboxSession:
        """The session for a conversation, created (object only) on first use."""
        safe = _safe_key(key)
        async with self._lock:
            session = self._sessions.get(safe)
            if session is None:
                session = SandboxSession(
                    safe,
                    workspace=self._work_root / safe,
                    sealed=self._sealed_root / f"{safe}.tar.enc.gz",
                    backend=self._backend,
                    vault=self._vault,
                    excludes=self._excludes,
                )
                self._sessions[safe] = session
            # Mark it freshly used so a reap sweep can't evict it out from under the
            # caller in the window between acquiring it and running on it.
            session.touch()
            return session

    async def start_preview(
        self, key: str, command: list[str], port: int
    ) -> PreviewHandle:
        """Start (or replace) the conversation's live preview and index its token."""
        session = await self.acquire(key)
        safe = _safe_key(key)
        token = secrets.token_urlsafe(32)
        # Launch outside the manager lock — the readiness wait must not stall other
        # conversations; the session's own lock marks it busy so the reaper defers.
        handle = await session.start_preview(
            command, port, token=token, startup_timeout_s=self._preview_startup_timeout_s
        )
        async with self._lock:
            self._drop_preview_tokens(safe)  # one preview per conversation
            self._previews[token] = safe
        return handle

    def resolve_preview(self, token: str) -> PreviewHandle | None:
        """The running preview a proxy request names, or None. Touches the session
        so active viewing keeps it warm (the idle reaper won't evict it). Sync (no
        await) so it reads the maps atomically against the reaper."""
        safe = self._previews.get(token)
        if safe is None:
            return None
        session = self._sessions.get(safe)
        if session is None or session.preview is None or session.preview.token != token:
            return None
        session.touch()
        return session.preview

    async def stop_preview(self, key: str) -> None:
        """Tear down the conversation's preview, leaving the exec session intact."""
        safe = _safe_key(key)
        async with self._lock:
            session = self._sessions.get(safe)
            self._drop_preview_tokens(safe)
            if session is not None:
                await session.stop_preview()

    def _drop_preview_tokens(self, safe: str) -> None:
        self._previews = {t: k for t, k in self._previews.items() if k != safe}

    async def start(self) -> None:
        self._reaper = asyncio.create_task(self._reaper_loop())

    async def stop(self) -> None:
        if self._reaper is not None:
            self._reaper.cancel()
            try:
                await self._reaper
            except asyncio.CancelledError:
                pass
            self._reaper = None
        async with self._lock:
            for session in list(self._sessions.values()):
                try:
                    await session.shutdown()
                except Exception:  # noqa: BLE001 — tear the rest down regardless
                    pass
            self._sessions.clear()
            self._previews.clear()

    async def _reaper_loop(self) -> None:
        while True:
            await asyncio.sleep(self._reap_interval)
            try:
                await self._sweep()
            except Exception:  # noqa: BLE001 — the reaper must survive a bad sweep
                pass

    async def _sweep(self) -> None:
        # Reaping seals the workspace; without the vault key we can't seal, and
        # killing the container would strand plaintext on disk. So defer all
        # reaping until the vault is unlocked rather than break encryption-at-rest.
        if not self._vault.is_unlocked:
            return
        now = time.monotonic()
        async with self._lock:
            stale = [
                key
                for key, s in self._sessions.items()
                if not s.is_busy and s.idle_seconds(now) >= self._idle_ttl
            ]
            # shutdown() runs under the manager lock so a concurrent acquire can't
            # mint a second session (same container name/workspace) mid-teardown;
            # the seal is off-thread, so the loop itself is not blocked.
            for key in stale:
                session = self._sessions.pop(key)
                self._drop_preview_tokens(key)
                try:
                    await session.shutdown()
                except Exception:  # noqa: BLE001 — one bad teardown must not stall the reaper
                    pass
