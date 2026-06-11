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
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path

from .base import Sandbox, SandboxError, SandboxResult, SandboxSpec

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


def _discover_runtime(preferred: str | None = None) -> str | None:
    """The first container runtime binary on PATH, honoring an explicit choice."""
    candidates = (preferred, *_RUNTIMES) if preferred else _RUNTIMES
    for name in candidates:
        if name and shutil.which(name):
            return name
    return None


def hardened_flags(
    *,
    network: bool,
    memory: str,
    cpus: str,
    pids_limit: int,
    workdir: str,
    mount: Path,
    env: Mapping[str, str],
) -> list[str]:
    """The isolation flags shared by every container we launch — egress off unless
    asked, all capabilities dropped, immutable root, only the workspace writable."""
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
    for key, value in env.items():
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
        return self._runtime or _discover_runtime()

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
            return await self.run_in(Path(tmp), spec)

    async def run_in(self, workspace: Path, spec: SandboxSpec) -> SandboxResult:
        """Run the spec in a throwaway container over a caller-owned workspace.

        Copies named inputs in and outputs back out; the workspace itself persists
        for the caller (the live-session network path reuses its session dir)."""
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
