"""One conversation's live sandbox — the warm-container model, for a single key.

A conversation gets one container, **lazily** created the first time the agent
runs code in it and kept alive so it can iterate: fix an error, re-run, reuse a
dependency it just installed — all against the same live process and filesystem,
without rebuilding. Nothing here is pre-created: a container is worth having only
once a conversation is actually running code in it.

Continuity survives a reap because the agent's files do. The workspace is a
host-side directory bind-mounted into the container; on reap we seal it (see
:mod:`services.sandbox.seal`) and remove the plaintext, then restore it the next
time the conversation runs code. So files persist encrypted-at-rest across reaps;
only the container's live process/system state is rebuilt.

There is one execution path and one fence. Every call ``exec``s into the live
container, which sits on this conversation's own ``--internal`` network with an
allowlisting proxy sidecar as its single exit (:mod:`services.sandbox.sidecar`).
Installing a package and burning CPU are what the workspace is *for* and cost no
approval; what is fenced is where bytes may go. So bringing a session up means
three objects, in order: the network, the sidecar, then the container that is
pointed at it.

A session knows only about itself. *When* it is created and *when* it is reaped are
policies over the whole set, and live in :mod:`services.sandbox.manager`.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import threading
import time
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Protocol

from core.fork import MergeReport
from core.vault import Vault

from .base import SandboxError, SandboxResult, SandboxSpec, contained_path
from .container import (
    _BACKSTOP_GRACE_S,
    IMAGE_PULL_TIMEOUT_S,
    ContainerSandbox,
    detached_run_argv,
    force_remove_container,
    hardened_flags,
    prepare_workspace,
    run_subprocess,
    runtime_fault_line,
    with_in_container_timeout,
)
from .fork import clone_workspace, fork_marker, manifest_of, merge_workspace
from .names import DEFAULT_NAMES, ContainerNames
from .preview import PreviewHandle, launch_preview, stop_preview_container
from .seal import partial_marker, restore_workspace, seal_workspace, walk_files
from .sidecar import (
    create_internal_network,
    proxy_env,
    remove_network,
    start_egress_sidecar,
    stop_egress_sidecar,
)
from .warmup import ImageWarmup

logger = logging.getLogger(__name__)

# How many times one `run` will bring the container up and exec. Two: the first attempt,
# and one rebuild-and-retry after a fault in the runtime itself. A third would be waiting
# out a container runtime that is genuinely broken, on the agent's clock.
_RUNTIME_FAULT_ATTEMPTS = 2

# Total wall clock one session's teardown may spend removing the boxes that could
# still hold its workspace mounted. A whole batch of them is tombstoned while this
# runs, and every `acquire()` for those conversations waits behind it with nothing to
# show the operator — so a runtime that has stopped answering costs a bounded pause,
# and what it did not manage to remove is left to the next boot's reconciliation.
_MOUNT_RELEASE_BUDGET_S = 10.0


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
    backend: ContainerSandbox,
    runtime: str,
    name: str,
    workspace: Path,
    *,
    network: str,
    env: Mapping[str, str],
) -> bytes | None:
    """Start one hardened, idle container over ``workspace``, kept alive with
    ``sleep infinity`` so later ``exec`` calls have something to land on. Returns ``None``
    on success, or the runtime's stderr on failure.

    A function rather than an inline argv because these flags *are* the containment —
    the workspace's internal network, resource caps, exactly one bind mount — and a
    second spelling of them somewhere else is a hole no test would notice.
    """
    argv = detached_run_argv(
        runtime,
        name,
        hardened_flags(
            network=network,
            memory=backend.memory,
            cpus=backend.cpus,
            pids_limit=backend.pids_limit,
            workdir=backend.workdir,
            mount=workspace,
            env=env,
        ),
        backend.image,
        ["sleep", "infinity"],
    )
    _timed_out, code, _out, err = await run_subprocess(argv, timeout_s=60.0)
    return None if code == 0 else err


class SandboxSession:
    """One conversation's live container plus its persistent workspace."""

    def __init__(
        self,
        key: str,
        *,
        workspace: Path,
        sealed: Path,
        egress_dir: Path,
        backend: ContainerSandbox,
        vault: Vault,
        excludes: Iterable[str],
        proxy_image: str = "python:alpine",
        warmup: ImageWarmup | None = None,
        ephemeral: bool = False,
        names: ContainerNames = DEFAULT_NAMES,
    ) -> None:
        self.key = key
        self._names = names
        self.workspace = workspace
        self.sealed = sealed
        # A fork taken for a delegated agent: a copy of a workspace that is already
        # archived under its parent's key. It is discarded rather than sealed wherever
        # an ordinary session would seal — see :meth:`shutdown`.
        self.ephemeral = ephemeral
        # The parent's files as they stood when this fork was taken, ``{relpath: sha256}``
        # — what :func:`services.sandbox.fork.merge_workspace` decides against. Empty on
        # every session that is not a fork.
        self.fork_manifest: dict[str, str] = {}
        # The host-side directory holding this workspace's allowlist, bind-mounted into
        # the sidecar. Owned by the egress policy, which rewrites it whenever the operator
        # approves a domain — the fence re-reads it, so a grant lands without a restart.
        self._egress_dir = egress_dir
        # Every runtime object this conversation owns is named after it, for the same
        # reason: a crash kills no container and removes no network, and an anonymous one
        # is a leftover that no teardown and no boot reconciliation could ever name.
        self.container = names.session(key)
        self._preview_container = names.preview(key)
        self._network = names.network(key)
        self._egress = names.sidecar(key)
        self._proxy_image = proxy_image
        self._backend = backend
        self._vault = vault
        self._excludes = tuple(excludes)
        self._warmup = warmup
        self._runtime: str | None = None
        self._running = False
        self._preview: PreviewHandle | None = None
        self._last_used = time.monotonic()
        self._lock = asyncio.Lock()
        # Guards the two multi-step disk transitions on this workspace against each
        # other: the seal (`_seal_and_clear`, run off-thread) and the restore/repair
        # (`_ensure_workspace`). They are reachable at the same instant because the
        # file tools deliberately take no session lock — a run parked on an approval
        # can be reaped and sealed while it still holds this session object, and its
        # next write would then repair the very directory the seal thread is walking.
        # Interleaved, the two leave a torn workspace with no fragment marker on it,
        # which the orphan sweep would seal straight over the good archive. A thread
        # lock rather than the asyncio one because both sides are synchronous and one
        # of them does not run on the loop at all; it is uncontended except in exactly
        # that race. Reentrant because `merge_fork` holds it across a restore that takes
        # it too.
        self._disk = threading.RLock()
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
        conversation). Raises :class:`SandboxError` if the server never serves.

        Brings the whole session up first, rather than only the preview container: the
        loopback port the operator's iframe loads is published by the sidecar, so a
        preview started into a workspace whose fence is not up has nothing to be reached
        through."""
        async with self._lock:
            self.touch()
            self._ensure_workspace()
            await self._ensure_up()
            runtime = self._backend.runtime
            if runtime is None:  # disappeared since detection — fail closed
                raise SandboxError("no container runtime available")
            await self._stop_preview_locked()
            handle = await launch_preview(
                runtime=runtime,
                backend=self._backend,
                workspace=self.workspace,
                container=self._preview_container,
                network=self._network,
                sidecar=self._egress,
                allow_dir=self._egress_dir,
                token=token,
                env=proxy_env(self._names, self.key),
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
            # Every box comes down before the archive goes on: each of them has this
            # workspace bind-mounted at /work, and sealing under a live mount archives
            # a torn tree and sends the box's later writes to a deleted inode.
            await self._stop_preview_locked()
            await self._release_mounts()
            self._running = False
            if self.ephemeral:
                # A fork's files were either merged back by now or abandoned, and an
                # archive of them would be a second at-rest copy of the parent's
                # workspace under a key nothing will ever ask for again.
                await asyncio.to_thread(self._drop_workspace)
                return
            if self.workspace.exists() and self._vault.is_unlocked:
                # Off-thread: tar+gzip+AEAD of a workspace must not block the loop.
                await asyncio.to_thread(self._seal_and_clear)
            # Vault locked ⇒ leave the plaintext workspace; the manager defers
            # reaping while locked, so a later (unlocked) reap seals it.

    def _seal_and_clear(self) -> None:
        """Archive the workspace and remove the plaintext — the only writer of the
        sealed copy, and the only place that decides an existing archive may be
        replaced.

        The one directory that must never be archived is a fragment (see
        :func:`~services.sandbox.seal.partial_marker`): it holds *less* than the archive
        it came from, so sealing it would drop every file the interrupted step had not
        reached yet, irrecoverably. There the archive wins and the fragment is simply
        dropped. Anything else is the conversation's current state and is sealed exactly
        as it stands — a workspace the agent was asked to empty included, since a
        deletion the operator asked for has to stick.

        Held under ``_disk`` for the whole archive-and-remove, so a file tool arriving
        on this same session mid-seal waits it out rather than repairing the directory
        underneath us (see ``_disk``)."""
        with self._disk:
            marker = partial_marker(self.workspace)
            if self.sealed.exists() and marker.exists():
                logger.info(
                    "sandbox: %s is a fragment of its own sealed archive — keeping the "
                    "archive and dropping the plaintext",
                    self.workspace.name,
                )
            else:
                self.sealed.parent.mkdir(parents=True, exist_ok=True)
                self.sealed.write_bytes(
                    seal_workspace(self.workspace, self._excludes, self._vault)
                )
            # Only now is the directory expendable: whatever survives the rmtree is a
            # fragment of an archive that is already on disk.
            marker.touch()
            shutil.rmtree(self.workspace, ignore_errors=True)
            marker.unlink(missing_ok=True)

    def _drop_workspace(self) -> None:
        """Remove a fork's plaintext, and the markers that describe it.

        Under ``_disk`` like the seal it replaces: a file tool arriving on this session
        mid-teardown must wait rather than repair the directory being removed."""
        with self._disk:
            shutil.rmtree(self.workspace, ignore_errors=True)
            fork_marker(self.workspace).unlink(missing_ok=True)
            partial_marker(self.workspace).unlink(missing_ok=True)

    async def discard(self) -> None:
        """Stop and kill this session's containers **without sealing** — the
        un-sealing counterpart to :meth:`shutdown`, run when a conversation is being
        deleted and before a fork's files are read back into its parent. Kills every
        container holding the workspace mount so what comes next — the manager's delete,
        or the merge's walk — has the directory to itself; it touches no disk itself, so
        disk cleanup has a single home (``SandboxSessionManager._purge_disk``)."""
        async with self._lock:
            await self._stop_preview_locked()
            await self._release_mounts()
            self._running = False

    async def _release_mounts(self) -> None:
        """Remove every container this conversation owns — then the network they were on —
        under one wall-clock budget for the lot.

        All three names, unconditionally, because "this session started it" is not the
        same question as "something is holding the mount". The orphan sweep builds a
        session over a directory some *earlier* process left behind, whose exec, preview
        and sidecar boxes may still be alive with that very directory mounted; and boot
        reconciliation, which would normally have cleared those, is skipped whenever the
        runtime was not up yet. The network comes last because it cannot be removed while
        anything is still attached. Best-effort and bounded, like every other removal — a
        daemon that has stopped answering must not park a teardown that a batch of
        tombstoned conversations is waiting on."""
        runtime = self._backend.runtime
        if runtime is None:
            return
        loop = asyncio.get_running_loop()
        deadline = loop.time() + _MOUNT_RELEASE_BUDGET_S
        for name in (self.container, self._preview_container, self._egress):
            left = deadline - loop.time()
            if left <= 0:
                logger.info("sandbox %s: gave up releasing the workspace mounts", self.key)
                return
            await force_remove_container(runtime, name, timeout_s=left)
        await remove_network(runtime, self._network, timeout_s=deadline - loop.time())

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
        for rel, full in walk_files(root, self._excludes):
            if len(files) >= max_files:
                return files
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

    def clone_into(self, child: Path) -> dict[str, str]:
        """Copy this workspace onto a fork's path, and record what it held at that moment.

        Blocking IO; call it off the event loop. ``_disk`` is held for the whole
        materialise-copy-and-hash, exactly as :meth:`merge_fork` holds it for the walk:
        a seal landing mid-copy rmtree's the very tree being read, which is either an
        error that kills the delegation or — worse — a torn copy whose manifest would
        record the tear as the fork point, so the merge back would read the parent's
        surviving files as never having existed.

        The manifest is hashed from the *copy*, which is the fork point by construction:
        re-reading this workspace afterwards would record a write it took since the clone
        as the base, and the merge back would then undo that write with the child's older
        copy.
        """
        with self._disk:
            self._ensure_workspace()
            clone_workspace(self.workspace, child)
            self.touch()
            return manifest_of(child, self._excludes)

    def merge_fork(self, child: Path, manifest: Mapping[str, str]) -> MergeReport:
        """Land what a fork of this workspace changed, and report what could not.

        Blocking IO; call it off the event loop. ``_disk`` is held for the whole
        walk-and-copy, with the workspace materialised *inside* that hold: a seal landing
        mid-merge archives a torn tree, and one that finished first leaves the merge
        recreating a few files where a whole workspace used to be — plaintext, unmarked,
        and exactly the shape the orphan sweep seals back over the good archive."""
        with self._disk:
            self._ensure_workspace()
            return merge_workspace(
                child=child, parent=self.workspace, manifest=manifest, excludes=self._excludes
            )

    def _ensure_workspace(self) -> None:
        # Under `_disk`, so a seal in flight finishes before we judge what is on disk:
        # the branch below throws a fragment away and restores over it, which against a
        # half-done seal would be two writers on one directory. See `_disk`.
        with self._disk:
            marker = partial_marker(self.workspace)
            if marker.exists():
                # A restore or a post-seal cleanup that never finished. The archive is
                # the whole copy, so throw the fragment away and let the restore below
                # run again rather than hand the agent half its files.
                shutil.rmtree(self.workspace, ignore_errors=True)
                marker.unlink(missing_ok=True)
            if not self.workspace.exists():
                if self.sealed.exists():
                    if not self._vault.is_unlocked:
                        raise SandboxError("cannot restore the sandbox workspace: vault is locked")
                    restore_workspace(self.sealed.read_bytes(), self.workspace, self._vault)
                else:
                    self.workspace.mkdir(parents=True, exist_ok=True)
            # The build-temp dir is dropped from the seal, so recreate it every time —
            # a missing TMPDIR breaks mktemp and silently shrinks pip's scratch space.
            prepare_workspace(self.workspace)

    async def _ensure_up(self) -> None:
        """Raise this conversation's fence, then the container that runs behind it.

        The order is the containment. The network exists before anything joins it, and the
        sidecar is up and answering before the box that will send its traffic there
        starts — so there is no window in which a workspace container is running with its
        exit policy not yet loaded. Any of the three failing raises, and nothing runs."""
        if self._running:
            return
        runtime = self._backend.runtime
        if runtime is None:  # disappeared since detection — fail closed
            raise SandboxError("no container runtime available")
        await self._await_image_ready()
        await self._kill_quietly(runtime)  # clear any stale same-named container
        subnet = await create_internal_network(runtime, self._network)
        await start_egress_sidecar(
            runtime,
            name=self._egress,
            network=self._network,
            subnet=subnet,
            allow_dir=self._egress_dir,
            image=self._proxy_image,
        )
        err = await _start_idle_container(
            self._backend,
            runtime,
            self.container,
            self.workspace,
            network=self._network,
            env=proxy_env(self._names, self.key),
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
        """Drop the whole fence, innermost first: a network cannot be removed while a
        container is still attached to it, so the containers go, then the sidecar, then
        the network. Used on the rebuild-and-retry path, where the next ``_ensure_up``
        raises all three again.

        The preview comes down with it. It is one of the containers on that network, and
        the loopback port it is reached on belongs to the sidecar — so a rebuild that left
        it running would leave the operator watching a port the new sidecar no longer
        publishes, with nothing anywhere reporting that it had stopped."""
        runtime = self._runtime
        if runtime is None:
            return
        await self._stop_preview_locked()
        await self._kill_quietly(runtime)
        await stop_egress_sidecar(runtime, self._egress)
        await remove_network(runtime, self._network)

    async def _kill_quietly(self, runtime: str) -> None:
        await force_remove_container(runtime, self.container)
