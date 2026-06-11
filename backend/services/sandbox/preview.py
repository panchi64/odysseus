"""Live-preview mechanics — a dev server the agent runs, reachable from the host.

The warm exec session is ``--network none`` and can't expose a port, so a live
preview is a **separate, long-lived container over the same workspace** (the way
the per-call egress path is a separate container over the same files), launched
with one in-container port published to an OS-assigned **loopback** host port.
The backend reverse-proxies that port out to a sandboxed iframe; only this host
can reach it. Kept apart from ``session`` so the session stays focused on the
exec lifecycle and this holds the launch / host-port / readiness details.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from .base import SandboxError
from .container import (
    ContainerSandbox,
    detached_run_argv,
    force_remove_container,
    hardened_flags,
    run_subprocess,
)

# How often to retry the readiness probe while the server boots.
_READY_POLL_INTERVAL_S = 0.25


@dataclass(frozen=True)
class PreviewHandle:
    """A running preview: the unguessable token that addresses it, the container
    backing it, and the loopback host port the proxy forwards to."""

    token: str
    container: str
    host_port: int
    container_port: int
    command: tuple[str, ...]

    @property
    def path(self) -> str:
        """The token-gated route the operator's iframe points at."""
        return f"/previews/{self.token}/"


async def launch_preview(
    *,
    runtime: str,
    backend: ContainerSandbox,
    workspace: Path,
    container: str,
    token: str,
    command: list[str],
    port: int,
    startup_timeout_s: float,
) -> PreviewHandle:
    """Start ``command`` as a detached server over ``workspace`` and wait until it
    is actually listening. Raises :class:`SandboxError` (with the container's log
    tail) if it never binds, so the caller can hand the reason back to the agent."""
    await stop_preview_container(runtime, container)  # clear any stale same-named one
    argv = detached_run_argv(
        runtime,
        container,
        hardened_flags(
            network=True,  # a published port needs a bridge network
            memory=backend.memory,
            cpus=backend.cpus,
            pids_limit=backend.pids_limit,
            workdir=backend.workdir,
            mount=workspace,
            env={},
            publish_port=port,
        ),
        backend.image,
        command,
    )
    _timed_out, code, _out, err = await run_subprocess(argv, timeout_s=60.0)
    if code != 0:
        raise SandboxError(f"failed to start preview server: {err.decode('utf-8', 'replace')}")

    try:
        host_port = await _published_host_port(runtime, container, port)
        await _await_listening(host_port, startup_timeout_s)
    except SandboxError as exc:
        tail = await _log_tail(runtime, container)
        await stop_preview_container(runtime, container)
        detail = f"{exc}" + (f"\n--- server logs ---\n{tail}" if tail else "")
        raise SandboxError(detail) from exc

    return PreviewHandle(
        token=token,
        container=container,
        host_port=host_port,
        container_port=port,
        command=tuple(command),
    )


async def stop_preview_container(runtime: str, container: str) -> None:
    """Tear down the preview container (the same best-effort kill the session uses)."""
    await force_remove_container(runtime, container)


async def _published_host_port(runtime: str, container: str, port: int) -> int:
    """The loopback host port the runtime assigned to the published container port."""
    _timed_out, code, out, err = await run_subprocess(
        [runtime, "port", container, f"{port}/tcp"], timeout_s=15.0
    )
    if code != 0:
        raise SandboxError(
            f"could not read the preview port: {err.decode('utf-8', 'replace').strip()}"
        )
    # Output is one or more `0.0.0.0:NNNNN` / `127.0.0.1:NNNNN` lines; take the port.
    for line in out.decode("utf-8", "replace").splitlines():
        host_port = line.rsplit(":", 1)[-1].strip()
        if host_port.isdigit():
            return int(host_port)
    raise SandboxError("the preview server did not publish a port")


async def _await_listening(host_port: int, timeout_s: float) -> None:
    """Poll the published port until a TCP connection succeeds, or time out."""
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
                    f"the preview server did not start listening within {timeout_s:.0f}s"
                ) from None
            await asyncio.sleep(_READY_POLL_INTERVAL_S)


async def _log_tail(runtime: str, container: str, *, lines: int = 50) -> str:
    """The container's last log lines, to explain a failed start to the agent."""
    try:
        _timed_out, _code, out, err = await run_subprocess(
            [runtime, "logs", "--tail", str(lines), container], timeout_s=10.0
        )
    except SandboxError:
        return ""
    return (out + err).decode("utf-8", "replace").strip()
