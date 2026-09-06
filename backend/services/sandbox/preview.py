"""Live-preview mechanics — a dev server the agent runs, reachable from the host.

The warm exec session runs the agent's own long-lived processes, so a live preview is a
**separate, long-lived container over the same workspace**, on the same workspace network
as everything else in the conversation.

It publishes nothing itself. A container attached to an ``--internal`` network cannot: the
runtime accepts ``--publish`` and maps no port at all, and the only box in a workspace with
a routable leg is the egress sidecar. So the sidecar owns the published loopback port and
relays it inward to ``<preview container>:<port>`` (:func:`services.sandbox.sidecar
.point_forwarder`), and this module points that relay at the container it just started.
The backend reverse-proxies the sidecar's host port out to a sandboxed iframe; only this
host can reach it.

Kept apart from ``session`` so the session stays focused on the exec lifecycle and this
holds the launch / host-port / readiness details.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from .base import SandboxError
from .container import (
    ContainerSandbox,
    await_http_serving,
    await_listening,
    container_running,
    detached_run_argv,
    force_remove_container,
    hardened_flags,
    published_host_port,
    run_subprocess,
)
from .egress_proxy import FORWARD_PORT
from .sidecar import point_forwarder


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

    def url_for(self, entry: str | None = None) -> str:
        """The proxy URL for a server ``entry`` path under this preview (e.g.
        ``"index.html"``), or the root when omitted. Owns the path-join so the
        ``/previews/{token}/`` scheme has one home, not a caller doing string math."""
        return self.path + (entry or "").lstrip("/")


async def launch_preview(
    *,
    runtime: str,
    backend: ContainerSandbox,
    workspace: Path,
    container: str,
    network: str,
    sidecar: str,
    allow_dir: Path,
    token: str,
    env: dict[str, str],
    command: list[str],
    port: int,
    startup_timeout_s: float,
) -> PreviewHandle:
    """Start ``command`` as a detached server over ``workspace`` and wait until it is
    actually serving. Raises :class:`SandboxError` (with the container's log tail) if it
    never does, so the caller can hand the reason back to the agent."""
    await stop_preview_container(runtime, container)  # clear any stale same-named one
    # Aimed before the server exists, not after: the sidecar reads the target per
    # connection, so the only thing that must be true by the time the operator's iframe
    # loads is that the file names this container.
    point_forwarder(allow_dir, f"{container}:{port}")
    argv = detached_run_argv(
        runtime,
        container,
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
        command,
    )
    _timed_out, code, _out, err = await run_subprocess(argv, timeout_s=60.0)
    if code != 0:
        raise SandboxError(f"failed to start preview server: {err.decode('utf-8', 'replace')}")

    try:
        # The sidecar's published port, not this container's — see the module docstring.
        host_port = await published_host_port(runtime, sidecar, FORWARD_PORT)
        # That port is the sidecar's and has been listening since the session came up, so
        # unlike a preview's own port it says nothing about the server: what answers here
        # is the relay, and only an HTTP reply proves something is behind it. Wait until
        # one arrives, so the iframe's first fetch (which fires the instant `view.live` is
        # emitted) lands on a real response instead of a transient error it would never
        # retry. Both probes share one budget so a slow bind can't double the worst case.
        deadline = asyncio.get_running_loop().time() + startup_timeout_s
        await await_listening(host_port, startup_timeout_s)
        serving = await await_http_serving(
            host_port, max(deadline - asyncio.get_running_loop().time(), 0.0)
        )
        # A server that is merely slow is still worth opening — the operator's refresh
        # button is the backstop. A container that has already exited is not: the command
        # was wrong, and the agent needs to be told that with the logs, not handed a URL
        # that will never answer.
        if not serving and not await container_running(runtime, container):
            raise SandboxError("the preview server exited without serving a request")
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


async def _log_tail(runtime: str, container: str, *, lines: int = 50) -> str:
    """The container's last log lines, to explain a failed start to the agent."""
    try:
        _timed_out, _code, out, err = await run_subprocess(
            [runtime, "logs", "--tail", str(lines), container], timeout_s=10.0
        )
    except SandboxError:
        return ""
    return (out + err).decode("utf-8", "replace").strip()
