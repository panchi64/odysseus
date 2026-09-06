"""The container-runtime sandbox backend — the portable default.

Drives a Docker- or Podman-compatible CLI to run a command in a container with
the host shut out: ``--cap-drop ALL``, ``--security-opt no-new-privileges``,
``--user uid:gid`` (never the image's root), explicit memory/PID/CPU caps, and a
network that is either nothing at all or one of a workspace's ``--internal``
networks. No host environment is passed — only ``spec.env``.

What the fence is *for* is exfiltration, not inconvenience. The wall that matters
is the one at the edge: the operator's real files are never mounted, and the only
route off the host is the allowlisting proxy a workspace's network carries
(:mod:`services.sandbox.sidecar`). Inside, what the box may write is decided
by ordinary file permissions and nothing else — the image's own tree is
root-owned and the box is not root, so ``/usr`` and friends stay unwritable
whether or not we ask the runtime for a read-only root, and the writable ground
is ``/work``, ``/tmp`` and the paths the image already left world-writable.

The workspace is a host-side directory bind-mounted at ``/work``: the only path
whose writes outlive the container, and the only place the host and the box
share. The one-shot ``run`` uses a throwaway temp dir; ``run_in`` operates over
a caller-owned directory.

We talk to the CLI over ``asyncio`` subprocesses (no SDK dependency — keeps the
runtime portable across hosts and the dependency surface small). The runtime
binary is auto-detected (Docker, then Podman) or pinned by config. The hardening
flags and the subprocess runner are module-level so the session backend, which
keeps a container alive, builds identical containers from the same primitives.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path

from core import net

from .base import Sandbox, SandboxError, SandboxResult, SandboxSpec, contained_path

logger = logging.getLogger(__name__)

# Candidate runtimes, in preference order. Both speak the same run/exec/version CLI.
_RUNTIMES = ("docker", "podman")

# How much longer the outer asyncio backstop waits than the in-container limit —
# enough to let the in-container `timeout` send SIGTERM then escalate to SIGKILL.
_BACKSTOP_GRACE_S = 15.0

# Budget for a fresh image pull (the ~150MB default slim image on a slow link).
# Shared by `ensure_image` itself and by anything that must *wait* on the
# background pull rather than race an implicit pull against a short
# container-create timeout (see `session.py`'s `_ensure_up`/`start_preview`).
IMAGE_PULL_TIMEOUT_S = 300.0

# Error text the container runtime itself emits when it — not the code it was asked
# to run — is what failed: a dead/broken container, a daemon that's down, or a stale
# workdir mount (e.g. Docker Desktop on macOS shares bind mounts by *path*, so a
# host-side rename of a mounted dir kills every later exec with an OCI cwd fault).
# The CLI prints these to stdout or stderr depending on version, so check both.
_RUNTIME_FAULT_MARKERS = (
    "oci runtime exec failed",
    "oci runtime error",
    "error response from daemon",
    "no such container",
    "container is not running",
    "unable to start container process",
    "cannot connect to the docker daemon",
)


def runtime_fault_line(exit_code: int, stdout: str, stderr: str) -> str | None:
    """The runtime's own error line when a non-zero exit came from the container
    runtime rather than the executed code, else ``None``.

    Matters because the two failures need opposite handling: a code failure goes
    back to the model to fix, while a runtime fault is infrastructure — the model
    can't fix it by editing its code, so the caller should rebuild/retry or report
    the environment as broken instead of presenting it as the code's fault."""
    if exit_code == 0:
        return None
    for stream in (stderr, stdout):
        low = stream.lower()
        for marker in _RUNTIME_FAULT_MARKERS:
            idx = low.find(marker)
            if idx == -1:
                continue
            start = stream.rfind("\n", 0, idx) + 1
            end = stream.find("\n", idx)
            return stream[start : end if end != -1 else len(stream)].strip()
    return None


def with_in_container_timeout(command: list[str], timeout_s: float) -> list[str]:
    """Wrap a command so the time limit is enforced *inside* the container.

    Killing the local CLI client does not stop the process running in the
    container, so we run the command under coreutils ``timeout`` (present in the
    default image): it sends SIGTERM at the deadline and SIGKILL shortly after,
    exiting 124 on timeout. The caller's outer wall-clock wait is only a backstop
    for a hung CLI/daemon."""
    return ["timeout", "--kill-after=5", str(timeout_s), *command]


def detached_run_argv(
    runtime: str, name: str, flags: list[str], image: str, command: list[str]
) -> list[str]:
    """The shared command line for a detached, named container — the envelope every
    long-lived box (the exec session, a preview server) starts from, so a hardening
    flag added to ``hardened_flags`` reaches them all and can't drift between paths."""
    return [runtime, "run", "--detach", "--name", name, *flags, image, *command]


async def force_remove_container(runtime: str, name: str, *, timeout_s: float = 30.0) -> None:
    """Best-effort ``runtime rm --force`` of a container — a missing one is fine.
    The single teardown primitive for every container we name (session + preview).

    Bounded, because a daemon that accepts the connection and never answers (a
    container whose mount is wedged, a Docker Desktop mid-restart) would otherwise
    park the caller here forever — and the callers are app startup and the reaper,
    neither of which may hang on a runtime having a bad day. Giving up only abandons
    the local client; the removal, if it lands at all, lands without us."""
    try:
        proc = await asyncio.create_subprocess_exec(
            runtime,
            "rm",
            "--force",
            name,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except (OSError, ValueError):
        return
    try:
        await asyncio.wait_for(proc.wait(), timeout=timeout_s)
    except TimeoutError:
        _kill(proc)
        logger.info("sandbox: gave up removing container %s after %.0fs", name, timeout_s)
    except asyncio.CancelledError:
        _kill(proc)
        raise


def discover_runtime(preferred: str | None = None) -> str | None:
    """The first container runtime binary on PATH, honoring an explicit choice.
    Shared by every backend that needs a runtime (the sandbox, the managed
    SearXNG instance) so the discovery rule lives in one place."""
    candidates = (preferred, *_RUNTIMES) if preferred else _RUNTIMES
    for name in candidates:
        if name and shutil.which(name):
            return name
    return None


async def published_host_port(runtime: str, container: str, port: int) -> int:
    """The loopback host port the runtime assigned to a published container port.

    Shared by every long-lived box that publishes a port (the live preview, the
    managed SearXNG instance). Raises :class:`SandboxError` if the runtime reports
    no published port for ``port``."""
    _timed_out, code, out, err = await run_subprocess(
        [runtime, "port", container, f"{port}/tcp"], timeout_s=15.0
    )
    if code != 0:
        raise SandboxError(
            f"could not read the published port: {err.decode('utf-8', 'replace').strip()}"
        )
    # Output is one or more `0.0.0.0:NNNNN` / `127.0.0.1:NNNNN` lines; take the port.
    for line in out.decode("utf-8", "replace").splitlines():
        host_port = line.rsplit(":", 1)[-1].strip()
        if host_port.isdigit():
            return int(host_port)
    raise SandboxError("the container did not publish a port")


async def await_log_marker(
    runtime: str,
    container: str,
    marker: bytes,
    *,
    timeout_s: float,
    poll_interval_s: float = 0.25,
) -> bool:
    """Poll a detached container's logs for the line it prints once ready, then confirm it
    is still running.

    The readiness probe for every sidecar we start that has no port of its own to knock on
    — the web fetcher's SSRF proxy and a workspace's egress proxy both announce themselves
    on stdout. The still-running check is the part that matters: a print-then-crash would
    otherwise leave the line in the log and mark a dead sidecar ready, and everything
    behind it would then fail one request at a time instead of failing to start."""
    for _ in range(int(timeout_s / poll_interval_s) + 1):
        _timed_out, _code, out, _err = await run_subprocess(
            [runtime, "logs", container], timeout_s=5.0
        )
        if marker in out:
            return await container_running(runtime, container)
        await asyncio.sleep(poll_interval_s)
    return False


async def container_running(runtime: str, container: str) -> bool:
    """Whether the runtime still reports this container as running.

    The question every readiness wait ends on: a port that never answered means one of
    two very different things depending on this — a server still warming up, or one that
    exited and never will. A container the runtime no longer knows at all answers False,
    which is the reading that matters."""
    _timed_out, _code, state, _err = await run_subprocess(
        [runtime, "inspect", "-f", "{{.State.Running}}", container], timeout_s=5.0
    )
    return b"true" in state.lower()


async def await_listening(
    host_port: int, timeout_s: float, *, poll_interval_s: float = 0.25
) -> None:
    """Poll a loopback host port until a TCP connection succeeds, or time out —
    the readiness probe shared by every server we wait on to bind. Thin wrapper over
    the neutral ``core.net`` probe that preserves the ``SandboxError`` contract its
    callers (sandbox sessions, previews, SearXNG, web fetch) already handle."""
    try:
        await net.await_listening(host_port, timeout_s, poll_interval_s=poll_interval_s)
    except TimeoutError as exc:
        raise SandboxError(str(exc)) from None


async def await_http_serving(
    host_port: int, timeout_s: float, *, poll_interval_s: float = 0.25
) -> bool:
    """Poll a loopback host port over HTTP until the server answers with a non-5xx
    status — a stronger readiness signal than :func:`await_listening` (a *bound* TCP
    port). A dev server binds its port well before it serves the entry page, and the
    iframe (whose first fetch fires the instant ``view.live`` is emitted) never retries
    a too-early load, so we wait until the server is actually answering.

    Returns whether it answered rather than raising on timeout — the caller is the one
    that knows whether a silent server is a slow one or a dead one. A connection error or
    a 5xx reply (a server still warming up) counts as not-yet-ready; a 2xx/3xx/4xx
    response means it is serving — the probe hits ``/`` while the iframe loads the entry
    path, so a 404 at the root still means "up". Each request and the polling sleep are
    bounded by the remaining budget, so the call never overshoots ``timeout_s`` even when
    a probe hangs."""
    return await net.await_http_ready(
        f"http://127.0.0.1:{host_port}/", timeout_s, poll_interval_s=poll_interval_s
    )


# Workspace-relative dirs the env defaults point at, created host-side before a run
# (see ``prepare_workspace``) so the very first command already finds them.
# ``.tmp`` backs ``TMPDIR`` (a missing one makes ``mktemp`` fail and Python's
# ``tempfile`` fall back to the in-memory ``/tmp`` tmpfs); ``.home`` backs ``HOME``
# so tool caches/config keyed off ``$HOME`` have somewhere writable. Both are sealed
# out (see ``Settings.sandbox_session_seal_excludes``), so they're scratch — kept
# off the encrypted archive and recreated each run.
_TMP_SUBDIR = ".tmp"
_HOME_SUBDIR = ".home"


def workspace_owner() -> str:
    """The ``uid:gid`` the container must run as so it can write the workspace.

    The bind-mounted ``/work`` is created host-side by **this** process and owned
    by its uid, mode 0755. We also ``--cap-drop ALL``, which strips
    ``CAP_DAC_OVERRIDE`` — so an in-container *root* (uid 0) is bound by ordinary
    permission bits and, owning none of ``/work``, cannot write it: every install
    redirect (``TMPDIR``, pip's ``--user`` target/cache) then fails, ``tempfile``
    falls back to the ``/tmp`` tmpfs, and nothing the agent installs survives the
    container. Running the box as the workspace's owner makes ``/work``
    writable without re-granting any capability, and keeps files the agent creates
    owned by this process so the seal/restore can read them."""
    return f"{os.getuid()}:{os.getgid()}"


def workspace_env_defaults(workdir: str) -> dict[str, str]:
    """Package-manager env so installs land in the *persistent* workspace rather
    than the container's throwaway layer: pip's ``--user`` target, its caches, the
    build temp, and a writable ``HOME`` all redirect under ``workdir`` (the
    bind-mount). Without this a plain ``pip install`` targets a system site-packages
    the non-root box does not own — and anything it did land would vanish with the
    container, so the agent would reinstall on every reap.

    ``PIP_USER`` makes a flagless ``pip install`` target user-site
    (``PYTHONUSERBASE``), which Python auto-adds to ``sys.path``; ``TMPDIR`` keeps
    wheel builds on the bind-mount rather than the ``/tmp`` tmpfs
    (``prepare_workspace`` creates it first). ``HOME`` is the catch-all for tools
    that key caches/config off ``$HOME``
    — it points at a seal-excluded subdir so that state stays writable but is
    dropped on reap instead of bloating the encrypted archive.

    ``PATH`` is deliberately **not** set: forcing it would override the configured
    image's own layout and break a non-Debian image. A ``--user`` console script
    therefore isn't on ``PATH`` by bare name — invoke it via ``python -m`` or its
    ``{workdir}/.local/bin/`` path."""
    return {
        "HOME": f"{workdir}/{_HOME_SUBDIR}",
        "PIP_USER": "1",
        "PYTHONUSERBASE": f"{workdir}/.local",
        "PIP_CACHE_DIR": f"{workdir}/.cache/pip",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "TMPDIR": f"{workdir}/{_TMP_SUBDIR}",
    }


def prepare_workspace(workspace: Path) -> None:
    """Create the writable scratch subdirs the env defaults reference before a run.

    ``TMPDIR`` must pre-exist — ``mktemp`` errors and ``tempfile`` falls back to the
    tmpfs when it's missing; ``HOME`` must exist or some tools refuse to start. pip
    creates its own ``--user``/cache dirs. Done host-side because the seal drops both
    dirs and the box may already be running when the next call arrives — writes to
    the bind-mount show up live inside it, so nothing has to be restarted."""
    for sub in (_TMP_SUBDIR, _HOME_SUBDIR):
        (workspace / sub).mkdir(parents=True, exist_ok=True)


def hardened_flags(
    *,
    network: str | None,
    memory: str,
    cpus: str,
    pids_limit: int,
    workdir: str,
    mount: Path,
    env: Mapping[str, str],
) -> list[str]:
    """The isolation flags shared by every container we launch — all capabilities
    dropped, never the image's root, resource caps, and no route out except the one
    ``network`` names.

    ``network`` is a network *name*, not a switch. ``None`` is ``--network none`` — a box
    with no interface at all, which is what a one-shot run over a throwaway directory
    wants. A name is one of a workspace's ``--internal`` networks
    (:mod:`services.sandbox.sidecar`), which is not egress either: nothing on it has a
    route off the host, and the proxy sidecar sharing it is the single exit. There is no
    spelling here that reaches the open web directly.

    Deliberately *not* here: a read-only root. It bought no containment that
    ``--user`` below does not already buy — the image's tree is root-owned and
    this box is not root, so ``/usr`` stays unwritable either way — while turning
    every world-writable scratch path (``/var/tmp``, ``/dev/shm``) into an error
    the agent could not act on. Those paths are writable again now, on the
    container's own overlay, and nothing here caps them: the flags below bound
    memory, CPU and processes, never bytes on the operator's disk.

    The ``/tmp`` tmpfs stays for what it *does* bound — it is RAM, charged to this
    box's memory cap and handed back whole when the box dies, so scratch written
    there can never outlive the run that made it.

    The caps are host protection, not agent restriction: one runaway box must not
    take the operator's machine down with it."""
    flags = [
        "--network",
        network or "none",
        "--cap-drop",
        "ALL",
        # Run as the workspace's host owner (this process), not the image's root:
        # with all caps dropped there's no CAP_DAC_OVERRIDE, so an in-container root
        # couldn't write the uid-owned /work and installs would fail. This is also
        # why system package managers (apt) can never work here — they need root
        # plus capabilities the box does not have. See ``workspace_owner``.
        "--user",
        workspace_owner(),
        "--security-opt",
        "no-new-privileges",
        # A gigabyte of scratch, not the old 64m, so a wheel build or an unpack that
        # lands here has room. It is RAM, though — tmpfs pages are charged to this
        # container's memory cap, so a run that filled it would be OOM-killed rather
        # than told ENOSPC. The bulk scratch the agent actually gets is TMPDIR on the
        # /work mount (see ``workspace_env_defaults``), which is real disk.
        "--tmpfs",
        "/tmp:rw,size=1g",
        "--memory",
        memory,
        "--cpus",
        cpus,
        "--pids-limit",
        str(pids_limit),
        "--workdir",
        workdir,
        "--volume",
        f"{mount}:{workdir}",
    ]
    # Redirect package installs into the writable workspace; an explicit spec env
    # always wins so a caller can override any default.
    merged = {**workspace_env_defaults(workdir), **env}
    for key, value in merged.items():
        flags += ["--env", f"{key}={value}"]
    return flags


async def run_subprocess(
    argv: list[str], *, stdin: str | None = None, timeout_s: float
) -> tuple[bool, int, bytes, bytes]:
    """Run a runtime command with a hard wall-clock timeout; kill on overrun.

    Returns ``(timed_out, exit_code, stdout, stderr)``. A timeout kills the local
    client and reports exit 124 (the conventional timeout code). Cancellation kills it
    too: the runtime client is a child process and does not go away because the task
    awaiting it did, so a bring-up cancelled mid-pull (app shutdown, a test tearing its
    app down) would otherwise leave `docker pull` running until its own five-minute
    budget expired — one per cancelled bring-up, each holding the network open."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except (OSError, ValueError) as exc:
        raise SandboxError(f"failed to start sandbox process: {exc}") from exc

    data = stdin.encode() if stdin is not None else None
    try:
        out, err = await asyncio.wait_for(proc.communicate(data), timeout=timeout_s)
    except TimeoutError:
        _kill(proc)
        await proc.wait()
        return True, 124, b"", b"sandbox execution timed out"
    except asyncio.CancelledError:
        # Kill without awaiting the reap: this task is already cancelled, so a further
        # await is not guaranteed to resume. The event loop's child watcher reaps it.
        _kill(proc)
        raise
    return False, proc.returncode or 0, out, err


def _kill(proc: asyncio.subprocess.Process) -> None:
    """Signal the child, tolerating one that has already exited."""
    try:
        proc.kill()
    except ProcessLookupError:
        pass


async def ensure_image(runtime: str, image: str) -> bool:
    """Pull ``image`` so it's cached before first use, **refreshing to the latest**
    for its tag on every call. If the pull fails (offline) fall back to a cached
    copy; return ``False`` only when neither a pull nor a cached copy yields the
    image. Shared by the managed SearXNG instance and the sandbox warm-up so both
    keep their image current with one rule."""
    _timed_out, code, _out, err = await run_subprocess(
        [runtime, "pull", image], timeout_s=IMAGE_PULL_TIMEOUT_S
    )
    if code == 0:
        return True
    logger.warning(
        "could not pull %s (%s); trying a cached copy",
        image,
        err.decode("utf-8", "replace").strip(),
    )
    _t, inspect_code, _o, _e = await run_subprocess(
        [runtime, "image", "inspect", image], timeout_s=15.0
    )
    if inspect_code != 0:
        logger.warning("no cached %s available", image)
        return False
    return True


class ContainerSandbox(Sandbox):
    """Runs a spec in a fresh, locked-down container and tears it down."""

    name = "container"

    def __init__(
        self,
        *,
        runtime: str | None = None,
        image: str = "python:3.12-slim",
        memory: str = "4g",
        cpus: str = "2.0",
        pids_limit: int = 1024,
        workdir: str = "/work",
    ) -> None:
        self._runtime = runtime
        self.image = image
        self.memory = memory
        self.cpus = cpus
        self.pids_limit = pids_limit
        self.workdir = workdir

    @property
    def runtime(self) -> str | None:
        """The resolved runtime binary (re-discovered if not pinned)."""
        return self._runtime or discover_runtime()

    async def available(self) -> bool:
        runtime = self.runtime
        if runtime is None:
            return False
        try:
            proc = await asyncio.create_subprocess_exec(
                runtime,
                "version",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except (OSError, ValueError):
            return False
        return await proc.wait() == 0

    def _flags(self, spec: SandboxSpec, mount: Path) -> list[str]:
        # No network at all: this backend's own path is the one-shot run over a throwaway
        # directory. A workspace that needs an exit runs through a session, which puts it
        # on its own internal network behind its own proxy (`services.sandbox.session`).
        return hardened_flags(
            network=None,
            memory=self.memory,
            cpus=self.cpus,
            pids_limit=self.pids_limit,
            workdir=self.workdir,
            mount=mount,
            env=spec.env,
        )

    def _run_argv(self, runtime: str, spec: SandboxSpec, mount: Path) -> list[str]:
        """The locked-down throwaway ``run`` command line — host shut out."""
        return [
            runtime,
            "run",
            "--rm",
            "--interactive",  # so stdin can be piped in
            *self._flags(spec, mount),
            self.image,
            *with_in_container_timeout(list(spec.command), spec.timeout_s),
        ]

    async def run(self, spec: SandboxSpec) -> SandboxResult:
        """One-shot: run the spec in a throwaway container over a fresh temp dir."""
        with tempfile.TemporaryDirectory(prefix="odysseus-sbx-") as tmp:
            workspace = Path(tmp)
            prepare_workspace(workspace)  # a fresh temp dir has none of the scratch dirs
            return await self.run_in(workspace, spec)

    async def run_in(self, workspace: Path, spec: SandboxSpec) -> SandboxResult:
        """Run the spec in a throwaway container over a caller-owned workspace.

        Copies named inputs in and outputs back out; the workspace itself persists for
        the caller. The caller owns workspace prep (``prepare_workspace``)."""
        runtime = self.runtime
        if runtime is None:  # disappeared since detection — fail closed, don't host-run
            raise SandboxError("no container runtime available")

        self._write_inputs(workspace, spec)
        backstop_timed_out, exit_code, out, err = await run_subprocess(
            self._run_argv(runtime, spec, workspace),
            stdin=spec.stdin,
            timeout_s=spec.timeout_s + _BACKSTOP_GRACE_S,
        )
        stdout = out.decode("utf-8", "replace")
        stderr = err.decode("utf-8", "replace")
        fault = runtime_fault_line(exit_code, stdout, stderr)
        if fault is not None:
            # The runtime, not the code, failed — report it as an environment
            # problem the model shouldn't try to "fix" by editing its code.
            raise SandboxError(f"the container runtime failed to run the code: {fault}")
        return SandboxResult(
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            # 124 is the in-container `timeout`'s exit on overrun; the backstop is
            # the rarer hung-CLI case. Either way the run timed out.
            timed_out=backstop_timed_out or exit_code == 124,
            outputs=self._read_outputs(workspace, spec),
        )

    @staticmethod
    def _write_inputs(mount: Path, spec: SandboxSpec) -> None:
        for f in spec.files:
            target = contained_path(mount, f.path, what="input path")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(f.content)

    @staticmethod
    def _read_outputs(mount: Path, spec: SandboxSpec) -> dict[str, bytes]:
        outputs: dict[str, bytes] = {}
        for name in spec.outputs:
            # Raises on an escape rather than skipping it. This site used to drop such
            # a name silently, which reported a traversal attempt as "the file wasn't
            # produced" — indistinguishable from an ordinary miss.
            path = contained_path(mount, name, what="output path")
            if path.is_file():
                outputs[name] = path.read_bytes()
        return outputs
