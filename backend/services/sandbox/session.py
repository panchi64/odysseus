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
import logging
import os
import re
import secrets
import shutil
import tarfile
import time
from collections.abc import Iterable
from fnmatch import fnmatch
from pathlib import Path
from typing import Protocol

from core.concurrency import gather_bounded
from core.vault import Vault

from .base import SandboxError, SandboxResult, SandboxSpec, contained_path
from .container import (
    _BACKSTOP_GRACE_S,
    IMAGE_PULL_TIMEOUT_S,
    ContainerSandbox,
    detached_run_argv,
    ensure_image,
    force_remove_container,
    hardened_flags,
    prepare_workspace,
    run_subprocess,
    runtime_fault_line,
    with_in_container_timeout,
)
from .preview import PreviewHandle, launch_preview, stop_preview_container

logger = logging.getLogger(__name__)

_SAFE = re.compile(r"[^A-Za-z0-9_.-]")

# How many reaped sessions are sealed concurrently (tar+gzip+AEAD is CPU/IO work
# off-thread) — bounded so a mass reap doesn't itself thrash the host, but no longer
# serial, so unrelated conversations aren't stalled behind one another. Shared by both
# reasons a session is reaped: the idle sweep, and a new session displacing an old one
# at the live-session cap.
_SEAL_CONCURRENCY = 3

# How many times one `run` will bring the container up and exec. Two: the first attempt,
# and one rebuild-and-retry after a fault in the runtime itself. A third would be waiting
# out a container runtime that is genuinely broken, on the agent's clock.
_RUNTIME_FAULT_ATTEMPTS = 2


def _safe_key(key: str) -> str:
    """A container/dir-safe token for a conversation id (leading char guaranteed)."""
    return "s" + _SAFE.sub("-", key)


class LiveWork(Protocol):
    """Just enough of a ``runs.Run`` for a session to know whether the work that claimed
    it is still going.

    A protocol rather than the class because the sandbox has no business depending on the
    run substrate to answer a question this small — and, more importantly, because a claim
    read this way is **released by asking, never by a hand-back**. The caller that would
    owe the hand-back is precisely the one that gets cancelled, times out, or dies with an
    unhandled error, and a claim leaked on those paths pins a container for the life of
    the process.
    """

    @property
    def is_terminal(self) -> bool: ...


async def _start_idle_container(
    backend: ContainerSandbox, runtime: str, name: str, workspace: Path
) -> bytes | None:
    """Start one hardened, idle container over ``workspace``, kept alive with
    ``sleep infinity`` so later ``exec`` calls have something to land on. Returns ``None``
    on success, or the runtime's stderr on failure.

    Both callers come through here — a conversation's own container and a pre-warmed
    spare — because these flags *are* the sandbox's containment: no network, a memory and
    CPU cap, a pid limit, and exactly one bind mount. Spelled out per call site, that set
    has two places to drift, and a spare that came up softer than a session's container is
    a hole no test would notice.
    """
    argv = detached_run_argv(
        runtime,
        name,
        hardened_flags(
            network=False,
            memory=backend.memory,
            cpus=backend.cpus,
            pids_limit=backend.pids_limit,
            workdir=backend.workdir,
            mount=workspace,
            env={},
        ),
        backend.image,
        ["sleep", "infinity"],
    )
    _timed_out, code, _out, err = await run_subprocess(argv, timeout_s=60.0)
    return None if code == 0 else err


class ImageWarmup:
    """Coordinates the background image pull (``SandboxSessionManager._warm_image``)
    with a session's first container create, so a cold ``_ensure_up``/
    ``start_preview`` never races an implicit ``docker run`` pull against its own
    short create-timeout (sandbox-01). One instance per manager, shared by every
    session it mints; a bare :class:`SandboxSession` used without one (e.g. direct
    unit construction) simply skips the coordination — see ``warmup=None``.

    Defaults to "nothing to wait for" (``ready``, not ``pending``) until
    :meth:`start_pulling` says otherwise — so a manager that's never actually
    started warming (e.g. most unit tests, which construct one without calling
    :meth:`SandboxSessionManager.start`) behaves exactly as it did before this
    coordination existed, rather than waiting on a pull that will never run."""

    def __init__(self) -> None:
        self._done = asyncio.Event()
        self._done.set()
        self.ready = True

    @property
    def pending(self) -> bool:
        """True only while a background pull is actually in flight."""
        return not self._done.is_set()

    def start_pulling(self) -> None:
        """Call right before kicking off the background pull — flips to
        pending so a concurrent create knows to wait rather than assume
        readiness."""
        self.ready = False
        self._done.clear()

    def mark_done(self, ready: bool) -> None:
        self.ready = ready
        self._done.set()

    async def wait(self, timeout_s: float) -> bool:
        """Wait up to ``timeout_s`` for the pull to resolve. Returns whether the
        image is now known ready. A caller that times out here still sees
        ``pending`` True afterwards, distinguishing "still pulling" (worth a
        clear retry message) from "resolved and confirmed missing" (let the
        ordinary create attempt run and report its own real error)."""
        if not self.pending:
            return self.ready
        try:
            await asyncio.wait_for(self._done.wait(), timeout=timeout_s)
        except TimeoutError:
            return False
        return self.ready


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
        warmup: ImageWarmup | None = None,
    ) -> None:
        self.key = key
        self.workspace = workspace
        self.sealed = sealed
        self.container = f"odysseus-sbx-{key}"
        self._preview_container = f"odysseus-pre-{key}"
        self._backend = backend
        self._vault = vault
        self._excludes = tuple(excludes)
        self._warmup = warmup
        self._runtime: str | None = None
        self._running = False
        self._preview: PreviewHandle | None = None
        self._last_used = time.monotonic()
        self._lock = asyncio.Lock()
        self._holders: list[LiveWork] = []

    @property
    def is_busy(self) -> bool:
        """A call is in flight on this session *right now* — one exec, one preview
        launch, one teardown. Deliberately narrow: it is the lock, and the lock spans a
        single call, not the turn the call belongs to. See :attr:`is_claimed`."""
        return self._lock.locked()

    def hold(self, holder: LiveWork | None) -> None:
        """Claim this session for a unit of work, until that work reaches a terminal
        state. Idempotent — re-claiming from the same run is what every later tool call
        in a turn does. ``None`` claims nothing: it is a caller with no lifetime to tie a
        container to (a proxy request, a route, a test), and it still costs the prune."""
        self._holders = [h for h in self._holders if not h.is_terminal and h is not holder]
        if holder is not None:
            self._holders.append(holder)

    @property
    def is_claimed(self) -> bool:
        """Whether a run that has not finished is still working in here.

        The gap this covers is the one the lock cannot: a turn is a *sequence* of execs
        with model thinking in between, and between two of them the session looks idle
        while being very much in use. Pruned on read rather than on release, because the
        run that would do the releasing is the one being cancelled."""
        self._holders = [h for h in self._holders if not h.is_terminal]
        return bool(self._holders)

    @property
    def is_displaceable(self) -> bool:
        """Whether displacing this session at the live-session cap would take it from
        nobody. Three ways it would not:

        - a call is in flight, and killing the container mid-exec fails the tool call the
          operator is watching;
        - a run that has not finished is between tool calls, and the seal drops
          ``node_modules``, ``.venv`` and ``.git`` by design — so the restore it comes
          back through hands that run a workspace missing exactly what it just spent
          minutes building;
        - a preview is live, and reaping it drops the token the proxy resolves, turning a
          page the operator may be looking at into a 404.

        The idle sweep asks a deliberately different question (busy, plus the TTL): a
        preview nobody has loaded in half an hour, or a run parked on an approval nobody
        answered, *should* be collected eventually. Time bounds everything; the count
        bounds only what nobody is using right now.
        """
        return not self.is_busy and not self.is_claimed and self._preview is None

    @property
    def is_warm(self) -> bool:
        """True when the live container is already up, so a run executes at once.
        False before the first run (or after a reap), when ``run()`` must first
        spin the container up — a cold start the caller may want to announce."""
        return self._running

    @property
    def preview(self) -> PreviewHandle | None:
        return self._preview

    def touch(self) -> None:
        self._last_used = time.monotonic()

    def idle_seconds(self, now: float) -> float:
        return now - self._last_used

    def _adopt_running_container(self, *, container: str, runtime: str) -> None:
        """Wire this session onto an already-running container (a claimed spare,
        sandbox-06) instead of the one ``_ensure_up`` would otherwise lazily
        start. The session was constructed over the spare's own workspace dir —
        the one the container's bind mount was established on."""
        self.container = container
        self._runtime = runtime
        self._running = True

    async def _await_image_ready(self) -> None:
        """Wait out an in-flight background image pull before creating a
        container, rather than let the create step's own implicit pull race a
        short create-timeout (sandbox-01). A caller with no ``warmup`` wired
        (e.g. a bare unit-constructed session) skips this outright."""
        if self._warmup is None or not self._warmup.pending:
            return
        ready = await self._warmup.wait(IMAGE_PULL_TIMEOUT_S)
        if not ready and self._warmup.pending:
            # Still unresolved after our own bounded wait — say so plainly
            # instead of racing another implicit pull against the create
            # step's short timeout below.
            raise SandboxError(
                "the sandbox image is still downloading; try again shortly"
            )

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
            # Still wait out an in-flight background image pull first, same as
            # `_ensure_up` below — otherwise this container's own implicit pull can
            # race the much shorter exec timeout on a genuinely cold boot (sandbox-01).
            await self._await_image_ready()
            return await self._backend.run_in(self.workspace, spec)
        # Two attempts, because a fault in the *runtime* (dead/broken container, daemon
        # hiccup, stale workdir mount) is not a fault in the code the model asked to run.
        # The workspace holds all durable state and the container is disposable, so a
        # rebuild-and-retry is cheap — and reporting a runtime fault to the model as if
        # its code had failed gives it an error it can only flail at.
        for attempt in range(_RUNTIME_FAULT_ATTEMPTS):
            await self._ensure_up()
            result = await self._exec_once(spec)
            fault = runtime_fault_line(result.exit_code, result.stdout, result.stderr)
            if fault is None:
                return result
            if attempt == _RUNTIME_FAULT_ATTEMPTS - 1:
                raise SandboxError(
                    f"the container runtime failed to execute the code even after a "
                    f"container rebuild: {fault}"
                )
            logger.warning(
                "sandbox %s: exec hit a runtime fault (%s); rebuilding the container",
                self.key,
                fault,
            )
            await self._kill()
            self._running = False
        raise AssertionError("unreachable")  # the loop always returns or raises

    async def _exec_once(self, spec: SandboxSpec) -> SandboxResult:
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
        target = contained_path(self.workspace, relpath)
        if not target.is_file():
            raise SandboxError(f"no such file in the sandbox: {relpath!r}")
        return target.read_bytes()

    def write_file(self, relpath: str, content: bytes) -> None:
        """Stage a file *into* this session's workspace, restoring it from the sealed
        copy first if the session was reaped. Writes the host-side bind-mount dir, so
        the next code run sees the file without spinning the container up here, and it
        survives a reap (it's inside the sealed workspace). Guards against escape —
        the same invariant as :meth:`read_file`, in reverse."""
        self._ensure_workspace()
        target = contained_path(self.workspace, relpath)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        self.touch()

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
            await self._await_image_ready()
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

    async def discard(self) -> None:
        """Stop and kill this session's containers **without sealing** — the
        un-sealing counterpart to :meth:`shutdown`, run when a conversation is being
        deleted. Kills the preview + exec containers (releasing the workspace mount)
        so the manager can then delete the files; it touches no disk itself, so disk
        cleanup has a single home (:meth:`SandboxSessionManager._purge_disk`)."""
        async with self._lock:
            await self._stop_preview_locked()
            if self._running:
                await self._kill()
                self._running = False

    def collect_text_files(
        self, *, max_file_bytes: int = 262_144, max_files: int = 2000
    ) -> dict[str, bytes]:
        """The workspace's text files (relpath → bytes) for a history snapshot — the
        same files the seal keeps, minus binaries and oversized ones. Prunes the
        excluded bloat (caches, virtualenvs, ``node_modules``, ``.git``), skips files
        over ``max_file_bytes`` and anything that isn't valid UTF-8. Empty when the
        workspace is cold (never run). Synchronous file IO — call off the event loop."""
        root = self.workspace
        if not root.exists():
            return {}
        files: dict[str, bytes] = {}
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if not _excluded(d, self._excludes))
            for name in sorted(filenames):
                if len(files) >= max_files:
                    return files
                full = Path(dirpath) / name
                if full.is_symlink():
                    continue
                rel = full.relative_to(root).as_posix()
                if _excluded(rel, self._excludes):
                    continue
                try:
                    if full.stat().st_size > max_file_bytes:
                        continue
                    data = full.read_bytes()
                except OSError:
                    continue
                if b"\x00" in data:
                    continue  # NUL byte ⇒ binary (a NUL is valid UTF-8, so the
                    # decode check below wouldn't catch it) — history is text only
                try:
                    data.decode("utf-8")
                except UnicodeDecodeError:
                    continue  # binary — skipped (history is code + text diffs)
                files[rel] = data
        return files

    def ensure_workspace(self) -> Path:
        """The workspace directory, materialized and ready to read or write, **without
        starting a container** — restoring it from the sealed archive first if the session
        was reaped. This is the seam the file tools bind to: browsing, reading and editing
        files costs no container start, only a cold session's tar restore.

        Counts as activity (``touch``), so a session being worked on purely through file
        tools is not reaped out from under the run that is using it."""
        self._ensure_workspace()
        self.touch()
        return self.workspace

    def _ensure_workspace(self) -> None:
        if not self.workspace.exists():
            if self.sealed.exists():
                if not self._vault.is_unlocked:
                    raise SandboxError("cannot restore the sandbox workspace: vault is locked")
                _restore_workspace(self.sealed.read_bytes(), self.workspace, self._vault)
            else:
                self.workspace.mkdir(parents=True, exist_ok=True)
        # The build-temp dir is dropped from the seal, so recreate it every time —
        # a missing TMPDIR breaks mktemp and silently shrinks pip's scratch space.
        prepare_workspace(self.workspace)

    async def _ensure_up(self) -> None:
        if self._running:
            return
        runtime = self._backend.runtime
        if runtime is None:  # disappeared since detection — fail closed
            raise SandboxError("no container runtime available")
        await self._await_image_ready()
        await self._kill_quietly(runtime)  # clear any stale same-named container
        err = await _start_idle_container(
            self._backend, runtime, self.container, self.workspace
        )
        if err is not None:
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


class _Spare:
    """An idle, conversation-unattached container pre-created off the critical
    path (sandbox-06) — same hardening as an ordinary session, ``sleep
    infinity``-parked over a neutral, never-written-to workspace. A cold
    ``acquire()`` claims one instead of paying the container-create round trip:
    the session adopts the container *and its workspace directory in place* —
    the dir is never renamed onto the conversation's canonical path, because a
    host-side rename under a live bind mount breaks it on VM-backed runtimes
    (Docker Desktop on macOS shares mounts by path, not dentry; every later
    ``exec`` then dies with an OCI cwd fault). Only a truly cold conversation
    (no plaintext workspace, no sealed archive) is eligible — adopting a spare's
    empty dir over existing state would skip the restore and the next reap would
    seal the empty dir over the real archive."""

    __slots__ = ("container", "workspace", "runtime", "created")

    def __init__(self, *, container: str, workspace: Path, runtime: str) -> None:
        self.container = container
        self.workspace = workspace
        self.runtime = runtime
        self.created = time.monotonic()


#: A session taken out of the live map and awaiting its seal, with the event that
#: releases whoever is waiting on *that* key's teardown. See ``_detach``.
type _Detached = tuple[str, SandboxSession, asyncio.Event]


class SandboxSessionManager:
    """Maps a conversation to its live :class:`SandboxSession`, reaping idle ones —
    idle for too long, or least-recently-used once there are too many.

    Built only when a container runtime is present (fail-closed detection lives in
    ``detect``), so its existence means code execution is available."""

    # How long a reaped/purged preview's token stays a recognized "stopped" tombstone
    # (`preview_status`) before it's pruned as stale — long enough for an operator who
    # left the tab open across the idle window to still get a legible answer when they
    # come back to it, short enough that an abandoned conversation's tokens don't
    # accumulate forever in memory.
    _STOPPED_TOKEN_TTL_S = 3600.0

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
        spare_enabled: bool = True,
        spare_count: int = 1,
        max_sessions: int = 8,
    ) -> None:
        self._backend = backend
        self._vault = vault
        self._work_root = data_dir / "sandbox" / "work"
        self._sealed_root = data_dir / "sandbox" / "sealed"
        self._idle_ttl = idle_ttl_s
        self._reap_interval = reap_interval_s
        self._excludes = tuple(excludes)
        self._preview_startup_timeout_s = preview_startup_timeout_s
        self._spare_enabled = spare_enabled
        self._spare_count = spare_count
        # How many conversations may hold a live container at once. The idle TTL bounds
        # a session in *time*; this bounds the set in *count*, which the TTL alone never
        # does — a dozen threads worked on in rotation each stay inside the window and
        # nothing is ever reaped. See `_over_cap`.
        self._max_sessions = max(1, max_sessions)
        self._sessions: dict[str, SandboxSession] = {}
        # token → safe session key, so the proxy route resolves a preview in O(1).
        self._previews: dict[str, str] = {}
        # token → monotonic time it was torn down *without* an explicit `view_close`
        # (idle-reaped or purged) — lets `preview_status` tell the frontend "this
        # server was killed out from under you" instead of a bare, indistinguishable
        # 404. Explicit closes don't need a tombstone: the model's `view_close` already
        # emits `view.live.stopped` on the live run stream.
        self._stopped_tokens: dict[str, float] = {}
        # safe key → set once its (former) session's teardown (a sweep's seal, or
        # a purge) is in flight. A concurrent acquire()/purge() for THIS key waits
        # on it; every other key is unaffected (sandbox-02).
        self._tearing_down: dict[str, asyncio.Event] = {}
        self._lock = asyncio.Lock()
        self._reaper: asyncio.Task | None = None
        self._warm: asyncio.Task | None = None
        # The pre-warmed spare pool (sandbox-06) — coordinates with the same
        # background image pull a cold session waits on, so a spare is never
        # created before the image it needs is actually cached.
        self._image_warmup = ImageWarmup()
        self._spares: list[_Spare] = []
        self._spare_seq = 0
        self._replenish_task: asyncio.Task | None = None
        # Seals in flight, owned by the manager rather than by whoever triggered them —
        # see `_tear_down`. Held so they are not garbage-collected mid-archive and so
        # `stop` can drain them.
        self._teardowns: set[asyncio.Task] = set()

    @property
    def image_warmup_pending(self) -> bool:
        """Whether the boot-time image pull is still in flight — lets a caller
        (e.g. the ``code_execute`` tool) distinguish an ordinary cold start from
        one that's actually waiting on a still-downloading image."""
        return self._image_warmup.pending

    def existing(self, key: str) -> SandboxSession | None:
        """The live session for a conversation if one exists, **without creating** it,
        so a turn that never touched the sandbox triggers no workspace/history work."""
        return self._sessions.get(_safe_key(key))

    async def acquire(self, key: str, *, holder: LiveWork | None = None) -> SandboxSession:
        """The session for a conversation, created (object only) on first use —
        claiming a pre-warmed spare (sandbox-06) if one is available. If this key
        is mid-teardown from a concurrent sweep/purge, waits for THAT teardown
        specifically rather than racing a second session onto the same workspace
        path; every other key proceeds immediately (sandbox-02).

        ``holder`` is the run asking, and claiming it here is what makes the cap safe:
        without it the only "in use" signal is the exec lock, which is held for one call
        out of the dozens a turn makes. See :attr:`SandboxSession.is_claimed`. Optional
        because not every caller is a turn — a proxy request resolving a preview, a route,
        a test — and those genuinely have no lifetime to tie a container to.

        Admitting a new session is also where the **cap** is applied: N live conversations
        is otherwise N containers, and the idle TTL alone only bounds that in time, never
        in count — thirty minutes of steady work across a dozen threads reaps nothing. So
        a new arrival reaps the least-recently-used idle sessions back down to the ceiling
        before it returns, which makes the ceiling a policy instead of an accident. Nothing
        is lost by the reap: a reaped session's files are sealed and restored the next time
        that conversation runs code, exactly as after an idle reap."""
        safe = _safe_key(key)
        evicted: list[_Detached] = []
        while True:
            async with self._lock:
                session = self._sessions.get(safe)
                if session is None:
                    other = self._tearing_down.get(safe)
                    if other is None:
                        spare = self._claim_spare(safe)
                        session = self._new_session(safe, spare=spare)
                        self._sessions[safe] = session
                        if spare is not None:
                            self._kick_replenish()
                        # Only a *new* arrival applies the cap: finding a session already
                        # live is the steady state, and re-reaping on every tool call
                        # would make the cap a per-call sweep.
                        evicted = self._detach(self._over_cap(keep=safe))
                if session is not None:
                    session.touch()
                    session.hold(holder)
                    break
            await other.wait()
        # Awaited rather than backgrounded, because the caller is about to start a
        # container: returning before the ones it displaced are actually gone would leave
        # the host over the cap at exactly the moment the cap matters. Awaited on a task
        # of the manager's own rather than inline, because the sessions being sealed
        # belong to *other* conversations — see `_tear_down`.
        await self._tear_down(evicted)
        return session

    def _over_cap(self, *, keep: str) -> list[str]:
        """The session keys to reap so the live set fits under the cap, longest-idle
        first. Called under the manager lock.

        Only a session nobody is using is a candidate — see
        :attr:`SandboxSession.is_displaceable` for the three ways that is decided. The cap
        is a resource ceiling, not a deadline: if everything live is in use the set simply
        runs over, and the ordinary idle sweep collects the overflow once the work
        finishes; the same choice ``ConversationStore._trim_cache`` makes about pinned
        trees, for the same reason.

        Reaping also *seals*, so it needs the vault key. With the vault locked there is
        nothing to do but run over the cap: tearing a container down without sealing would
        strand the agent's plaintext files on disk, which is a worse answer than a
        container too many."""
        if not self._vault.is_unlocked:
            return []
        overflow = len(self._sessions) - self._max_sessions
        if overflow <= 0:
            return []
        now = time.monotonic()
        idle = sorted(
            (
                (session.idle_seconds(now), key)
                for key, session in self._sessions.items()
                if key != keep and session.is_displaceable
            ),
            reverse=True,
        )
        return [key for _, key in idle[:overflow]]

    def _detach(self, keys: Iterable[str]) -> list[_Detached]:
        """Take sessions out of the live map, leaving a per-key teardown tombstone
        behind. Called under the manager lock, by both reasons a session is reaped: the
        idle sweep and the live-session cap.

        Detaching and sealing are separate halves on purpose. The map mutation has to be
        atomic against a concurrent ``acquire()``/``purge()`` — otherwise a second session
        is minted onto a workspace mid-teardown — while the seal itself is slow and must
        not hold the lock for the sum of every teardown (sandbox-02). The returned events
        are what the *same* key's acquire/purge waits on; every other key proceeds."""
        detached: list[_Detached] = []
        for key in keys:
            session = self._sessions.pop(key, None)
            if session is None:
                continue
            self._mark_preview_stopped(session)
            self._drop_preview_tokens(key)
            event = asyncio.Event()
            self._tearing_down[key] = event
            detached.append((key, session, event))
        return detached

    async def _tear_down(self, detached: list[_Detached]) -> None:
        """Seal detached sessions on a task the *manager* owns, and wait for it.

        The waiting is the caller's; the sealing is not. Both reasons a session is
        detached tear down somebody else's conversation — the cap seals whoever was
        least-recently-used, the sweep seals whoever went idle — and neither of them
        should die because the task that happened to trigger it was cancelled. Sealing
        is seconds of tar+gzip+AEAD, so the window is wide: the operator presses Stop on
        their own run, the acquiring task unwinds, and an unrelated conversation is left
        with a plaintext workspace on disk, no archive, and a live container that is in
        nobody's map for any sweep to ever find.

        ``shield`` is what separates the two: a cancelled caller stops waiting, and the
        seal it started finishes regardless. :meth:`stop` drains what is still in flight
        rather than cancelling it — a half-written archive is the one outcome worse than
        a slow shutdown."""
        if not detached:
            return
        task = asyncio.create_task(self._seal_detached(detached))
        self._teardowns.add(task)
        task.add_done_callback(self._teardowns.discard)
        await asyncio.shield(task)

    async def _seal_detached(self, detached: list[_Detached]) -> None:
        """Seal and tear down detached sessions off the manager lock, a few at a time,
        then release each one's tombstone. One failed teardown must not strand the others
        — or, worse, leave a tombstone set forever and hang every later acquire for that
        conversation — so each leg isolates its own failure and releases in a ``finally``."""

        async def seal(key: str, session: SandboxSession, event: asyncio.Event) -> None:
            sealed = False
            try:
                await session.shutdown()
                sealed = True
            except Exception:  # noqa: BLE001 — one bad teardown must not stall the rest
                logger.warning(
                    "sandbox %s: teardown failed; leaving the session live for the sweep",
                    key,
                    exc_info=True,
                )
            finally:
                async with self._lock:
                    if not sealed:
                        # A seal that did not happen must not lose the session with it.
                        # Dropped here it would be a container out of every map — no
                        # sweep can reach it, no purge names it, and its workspace stays
                        # plaintext on disk — so put it back and let the idle sweep try
                        # again. Nothing can have taken the key meanwhile: holding
                        # acquire and purge off until this line is what the tombstone
                        # `_detach` left is for.
                        self._sessions.setdefault(key, session)
                    self._tearing_down.pop(key, None)
                event.set()

        await gather_bounded([seal(*item) for item in detached], _SEAL_CONCURRENCY)

    def _claim_spare(self, safe: str) -> _Spare | None:
        """Pop a spare for this key, but only for a **truly cold** conversation —
        no plaintext workspace and no sealed archive on disk. An adopted spare
        keeps its own (empty) workspace, so adopting over existing state would
        bypass ``_ensure_workspace``'s restore, and the next reap would then seal
        the near-empty spare dir over the real archive, destroying it."""
        if not self._spares:
            return None
        has_state = (self._work_root / safe).exists() or (
            self._sealed_root / f"{safe}.tar.enc.gz"
        ).exists()
        return None if has_state else self._spares.pop()

    def _new_session(self, safe: str, *, spare: _Spare | None) -> SandboxSession:
        # An adopted spare keeps its own workspace dir: its container's bind
        # mount was established on that path, and renaming a mounted dir on the
        # host breaks the mount on VM-backed runtimes (Docker Desktop on macOS
        # resolves shared mounts by path, not dentry) — every later exec would
        # die with an OCI cwd fault.
        session = SandboxSession(
            safe,
            workspace=spare.workspace if spare is not None else self._work_root / safe,
            sealed=self._sealed_root / f"{safe}.tar.enc.gz",
            backend=self._backend,
            vault=self._vault,
            excludes=self._excludes,
            warmup=self._image_warmup,
        )
        if spare is not None:
            session._adopt_running_container(container=spare.container, runtime=spare.runtime)
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

    def preview_status(self, token: str) -> str:
        """Whether a `view.live` token still names a running preview, was torn down
        without an explicit stop (idle-reaped or the conversation was purged), or is
        unrecognized. Read-only — unlike `resolve_preview`, a status check must not
        itself keep an otherwise-idle preview warm. Lets the frontend tell "the
        sandbox went idle and killed it" apart from a merely-still-loading iframe."""
        safe = self._previews.get(token)
        if safe is not None:
            session = self._sessions.get(safe)
            if session is not None and session.preview is not None:
                if session.preview.token == token:
                    return "running"
        return "stopped" if token in self._stopped_tokens else "unknown"

    def _mark_preview_stopped(self, session: SandboxSession) -> None:
        """Tombstone a session's preview token as stopped-without-a-signal (idle
        reap or purge) and prune stale tombstones. Call *before* the session's
        preview is torn down."""
        now = time.monotonic()
        cutoff = now - self._STOPPED_TOKEN_TTL_S
        self._stopped_tokens = {t: ts for t, ts in self._stopped_tokens.items() if ts > cutoff}
        if session.preview is not None:
            self._stopped_tokens[session.preview.token] = now

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

    async def purge(self, key: str) -> None:
        """Delete a conversation's sandbox outright — stop any live session and
        remove its workspace **and** sealed archive from disk. Called when the
        conversation is deleted, so nothing is kept. Idempotent and safe for a cold
        conversation (no live session, only a sealed archive on disk), and works
        while the vault is locked (it only destroys).

        Registers itself in ``_tearing_down`` (the same gate a sweep's seal uses)
        for the duration of its own teardown+delete: if a sweep is already mid-seal
        for this key we wait for that first, and a concurrent ``acquire()`` for
        this key waits for us in turn — so nothing ever recreates a session onto
        files we're in the middle of removing (sandbox-02)."""
        safe = _safe_key(key)
        my_event = asyncio.Event()
        session: SandboxSession | None = None
        while True:
            async with self._lock:
                other = self._tearing_down.get(safe)
                if other is None:
                    session = self._sessions.pop(safe, None)
                    if session is not None:
                        self._mark_preview_stopped(session)
                        self._drop_preview_tokens(safe)
                    self._tearing_down[safe] = my_event
                    break
            await other.wait()
        try:
            if session is not None:
                await session.discard()
            workspace = session.workspace if session is not None else None
            await asyncio.to_thread(self._purge_disk, safe, workspace)
        finally:
            async with self._lock:
                self._tearing_down.pop(safe, None)
            my_event.set()

    def _purge_disk(self, safe: str, workspace: Path | None = None) -> None:
        # A live session's workspace may not sit at the canonical path (an adopted
        # spare keeps its own dir), so remove both it and the canonical dir.
        if workspace is not None:
            shutil.rmtree(workspace, ignore_errors=True)
        shutil.rmtree(self._work_root / safe, ignore_errors=True)
        (self._sealed_root / f"{safe}.tar.enc.gz").unlink(missing_ok=True)

    async def start(self) -> None:
        """Launch the idle reaper and warm the shared container image in the
        background. A boot status line for code execution and previews is logged
        here (both share this manager's runtime + image); the image pull runs off
        the critical path so app startup is never blocked, then logs when ready."""
        self._reaper = asyncio.create_task(self._reaper_loop())
        runtime = self._backend.runtime
        image = self._backend.image
        logger.info("sandbox: code execution ready (runtime=%s) — warming image %s", runtime, image)
        logger.info("preview: ready (runtime=%s) — shares the sandbox image %s", runtime, image)
        self._warm = asyncio.create_task(self._warm_image())

    async def _warm_image(self) -> None:
        """Pull the latest container image so the first code run / preview doesn't
        pay the pull cost. Best-effort: a failure leaves the image to be pulled
        lazily on first use rather than blocking or crashing startup. Resolves
        ``_image_warmup`` either way, so any session waiting on it (sandbox-01)
        and the spare pool (sandbox-06, which only pre-creates once the image is
        confirmed cached) both unblock."""
        self._image_warmup.start_pulling()
        runtime = self._backend.runtime
        if runtime is None:  # disappeared since detection — nothing to warm
            self._image_warmup.mark_done(False)
            return
        image = self._backend.image
        try:
            ready = await ensure_image(runtime, image)
        except Exception:  # noqa: BLE001 — warming must never crash the background task
            logger.exception("sandbox: image warm-up failed unexpectedly")
            self._image_warmup.mark_done(False)
            return
        if ready:
            logger.info("sandbox: image %s ready", image)
            logger.info("preview: image %s ready", image)
        else:
            logger.warning(
                "sandbox/preview: image %s unavailable — first run will pull it on demand",
                image,
            )
        self._image_warmup.mark_done(ready)
        self._kick_replenish()

    def _kick_replenish(self) -> None:
        """Top the spare pool back up in the background — after the image is
        confirmed ready, after a spare is claimed, and after a stale one is
        reaped. A no-op while a replenish is already in flight."""
        if not self._spare_enabled:
            return
        if self._replenish_task is None or self._replenish_task.done():
            self._replenish_task = asyncio.create_task(self._replenish_spares())

    async def _replenish_spares(self) -> None:
        """Create idle, conversation-unattached containers up to ``spare_count``
        (sandbox-06), entirely off the request path. Waits for the image to be
        confirmed ready first (never races the boot pull); if the image turned
        out unavailable, skips silently — the ordinary lazy per-conversation path
        will report the real reason when something actually tries to use it."""
        if not self._spare_enabled or self._image_warmup.pending or not self._image_warmup.ready:
            return
        runtime = self._backend.runtime
        if runtime is None:
            return
        while len(self._spares) < self._spare_count:
            try:
                spare = await self._create_spare(runtime)
            except SandboxError:
                logger.warning("sandbox: could not pre-warm a spare container", exc_info=True)
                return
            self._spares.append(spare)

    async def _create_spare(self, runtime: str) -> _Spare:
        """One idle spare: a hardened container over a fresh, neutral workspace
        directory that nothing has written to yet, kept alive with the same
        ``sleep infinity`` pattern a session's own container uses."""
        self._spare_seq += 1
        token = secrets.token_hex(4)
        name = f"odysseus-sbx-spare-{self._spare_seq}-{token}"
        workspace = self._work_root / f"_spare-{self._spare_seq}-{token}"
        workspace.mkdir(parents=True, exist_ok=True)
        prepare_workspace(workspace)
        err = await _start_idle_container(self._backend, runtime, name, workspace)
        if err is not None:
            shutil.rmtree(workspace, ignore_errors=True)
            raise SandboxError(
                f"failed to pre-warm a spare container: {err.decode('utf-8', 'replace')}"
            )
        return _Spare(container=name, workspace=workspace, runtime=runtime)

    async def stop(self) -> None:
        for task in (self._reaper, self._warm, self._replenish_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._reaper = None
        self._warm = None
        self._replenish_task = None
        # Drained, never cancelled: a seal interrupted mid-archive leaves a workspace
        # neither sealed nor plaintext-free. Drained *before* taking the lock, which is
        # what each of them needs to release its own tombstone.
        if self._teardowns:
            await asyncio.gather(*self._teardowns, return_exceptions=True)
        async with self._lock:
            for session in list(self._sessions.values()):
                try:
                    await session.shutdown()
                except Exception:  # noqa: BLE001 — tear the rest down regardless
                    pass
            self._sessions.clear()
            self._previews.clear()
            spares, self._spares = self._spares, []
        for spare in spares:
            await force_remove_container(spare.runtime, spare.container)
            await asyncio.to_thread(shutil.rmtree, spare.workspace, ignore_errors=True)

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
            # Snapshot + detach under the lock (so a concurrent acquire() can't
            # mint a second session onto the same workspace mid-teardown), but the
            # seal itself (tar+gzip+AEAD, potentially slow) runs OUTSIDE the lock,
            # a few at a time — a mass reap must not stall unrelated conversations'
            # acquire()/start_preview()/purge() for the sum of every seal (sandbox-02).
            # A per-key tombstone in `_tearing_down` lets that *same* key's acquire/
            # purge wait for its own teardown specifically, never anyone else's.
            detached = self._detach(stale)
            stale_spares = [s for s in self._spares if now - s.created >= self._idle_ttl]
            for spare in stale_spares:
                self._spares.remove(spare)

        await self._tear_down(detached)

        for spare in stale_spares:
            await force_remove_container(spare.runtime, spare.container)
            await asyncio.to_thread(shutil.rmtree, spare.workspace, ignore_errors=True)
        if stale_spares:
            self._kick_replenish()
