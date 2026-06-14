"""The container-runtime sandbox backend — the portable default.

Drives a Docker- or Podman-compatible CLI to run a command in a locked-down
container with the host shut out: ``--network none`` by default, ``--cap-drop
ALL``, ``--security-opt no-new-privileges``, a **read-only root** with a writable
``/work`` (the workspace) and a small ``tmpfs`` for scratch, and explicit
memory/PID/CPU caps. No host environment is passed — only ``spec.env``.

The workspace is a host-side directory bind-mounted at ``/work``: the container
reads/writes only there, and the operator's real files are never mounted, so the
box cannot reach the host filesystem. The one-shot ``run`` uses a throwaway temp
dir; ``run_in`` operates over a caller-owned directory (the live-session path).

We talk to the CLI over ``asyncio`` subprocesses (no SDK dependency — keeps the
runtime portable across hosts and the dependency surface small). The runtime
binary is auto-detected (Docker, then Podman) or pinned by config. The hardening
flags and the subprocess runner are module-level so the session backend, which
keeps a container alive, builds identical containers from the same primitives.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path

from .base import Sandbox, SandboxError, SandboxResult, SandboxSpec

logger = logging.getLogger(__name__)

# Candidate runtimes, in preference order. Both speak the same run/exec/version CLI.
_RUNTIMES = ("docker", "podman")

# How much longer the outer asyncio backstop waits than the in-container limit —
# enough to let the in-container `timeout` send SIGTERM then escalate to SIGKILL.
_BACKSTOP_GRACE_S = 15.0


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


async def force_remove_container(runtime: str, name: str) -> None:
    """Best-effort ``runtime rm --force`` of a container — a missing one is fine.
    The single teardown primitive for every container we name (session + preview)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            runtime,
            "rm",
            "--force",
            name,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
    except (OSError, ValueError):
        pass


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


async def await_listening(
    host_port: int, timeout_s: float, *, poll_interval_s: float = 0.25
) -> None:
    """Poll a loopback host port until a TCP connection succeeds, or time out —
    the readiness probe shared by every server we wait on to bind."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while True:
        try:
            _reader, writer = await asyncio.open_connection("127.0.0.1", host_port)
            writer.close()
            await writer.wait_closed()
            return
        except (OSError, ConnectionError):
            if loop.time() >= deadline:
                raise SandboxError(
                    f"the server did not start listening within {timeout_s:.0f}s"
                ) from None
            await asyncio.sleep(poll_interval_s)


# Workspace-relative dirs the env defaults point at, created host-side before a
# run (see ``prepare_workspace``) because the container's root is read-only.
# ``.tmp`` backs ``TMPDIR`` (a missing one makes ``mktemp`` fail and Python's
# ``tempfile`` fall back to the tiny ``/tmp`` tmpfs); ``.home`` backs ``HOME`` so
# tool caches/config keyed off ``$HOME`` have somewhere writable. Both are sealed
# out (see ``Settings.sandbox_session_seal_excludes``), so they're scratch — kept
# off the encrypted archive and recreated each run.
_TMP_SUBDIR = ".tmp"
_HOME_SUBDIR = ".home"


def workspace_env_defaults(workdir: str) -> dict[str, str]:
    """Package-manager env so installs land in the writable workspace, not the
    read-only root: pip's ``--user`` target, its caches, the build temp, and a
    writable ``HOME`` all redirect under ``workdir`` (the persisted bind-mount).
    Without this a plain ``pip install`` tries to write the immutable root and fails.

    ``PIP_USER`` makes a flagless ``pip install`` target user-site
    (``PYTHONUSERBASE``), which Python auto-adds to ``sys.path``; ``TMPDIR`` keeps
    wheel builds off the tiny ``/tmp`` tmpfs (``prepare_workspace`` creates it
    first). ``HOME`` is the catch-all for tools that key caches/config off ``$HOME``
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
    small tmpfs when it's missing; ``HOME`` must exist or some tools refuse to start.
    pip creates its own ``--user``/cache dirs. The container's read-only root can't
    ``mkdir`` these, so we do it host-side on the bind-mount (changes are visible
    live in the running session container)."""
    for sub in (_TMP_SUBDIR, _HOME_SUBDIR):
        (workspace / sub).mkdir(parents=True, exist_ok=True)


def hardened_flags(
    *,
    network: bool,
    memory: str,
    cpus: str,
    pids_limit: int,
    workdir: str,
    mount: Path,
    env: Mapping[str, str],
    publish_port: int | None = None,
) -> list[str]:
    """The isolation flags shared by every container we launch — egress off unless
    asked, all capabilities dropped, immutable root, only the workspace writable.

    ``publish_port`` (the live-preview path only) maps an in-container port out to
    an OS-assigned host port bound to loopback, so only this host reaches the
    preview server — never the LAN."""
    flags = [
        "--network",
        "bridge" if network else "none",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--read-only",  # root fs immutable; only the mount + tmpfs are writable
        "--tmpfs",
        "/tmp:rw,size=64m",
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
    if publish_port is not None:
        flags += ["--publish", f"127.0.0.1:0:{publish_port}"]
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
    client and reports exit 124 (the conventional timeout code)."""
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
        proc.kill()
        await proc.wait()
        return True, 124, b"", b"sandbox execution timed out"
    return False, proc.returncode or 0, out, err


async def ensure_image(runtime: str, image: str) -> bool:
    """Pull ``image`` so it's cached before first use, **refreshing to the latest**
    for its tag on every call. If the pull fails (offline) fall back to a cached
    copy; return ``False`` only when neither a pull nor a cached copy yields the
    image. Shared by the managed SearXNG instance and the sandbox warm-up so both
    keep their image current with one rule."""
    _timed_out, code, _out, err = await run_subprocess(
        [runtime, "pull", image], timeout_s=300.0
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
        memory: str = "512m",
        cpus: str = "1.0",
        pids_limit: int = 256,
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
        return hardened_flags(
            network=spec.network,
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

        Copies named inputs in and outputs back out; the workspace itself persists
        for the caller (the live-session network path reuses its session dir). The
        caller owns workspace prep (``prepare_workspace``) — the session path has
        already done it via ``_ensure_workspace``, so we don't repeat it here."""
        runtime = self.runtime
        if runtime is None:  # disappeared since detection — fail closed, don't host-run
            raise SandboxError("no container runtime available")

        self._write_inputs(workspace, spec)
        backstop_timed_out, exit_code, out, err = await run_subprocess(
            self._run_argv(runtime, spec, workspace),
            stdin=spec.stdin,
            timeout_s=spec.timeout_s + _BACKSTOP_GRACE_S,
        )
        return SandboxResult(
            exit_code=exit_code,
            stdout=out.decode("utf-8", "replace"),
            stderr=err.decode("utf-8", "replace"),
            # 124 is the in-container `timeout`'s exit on overrun; the backstop is
            # the rarer hung-CLI case. Either way the run timed out.
            timed_out=backstop_timed_out or exit_code == 124,
            outputs=self._read_outputs(workspace, spec),
        )

    @staticmethod
    def _write_inputs(mount: Path, spec: SandboxSpec) -> None:
        for f in spec.files:
            target = (mount / f.path).resolve()
            if not target.is_relative_to(mount.resolve()):  # no ../ escape from the box
                raise SandboxError(f"input path escapes the sandbox: {f.path!r}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(f.content)

    @staticmethod
    def _read_outputs(mount: Path, spec: SandboxSpec) -> dict[str, bytes]:
        outputs: dict[str, bytes] = {}
        for name in spec.outputs:
            path = (mount / name).resolve()
            if path.is_relative_to(mount.resolve()) and path.is_file():
                outputs[name] = path.read_bytes()
        return outputs
