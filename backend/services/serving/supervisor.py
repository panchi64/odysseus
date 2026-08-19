"""ProcessSupervisor — spawn and supervise an engine subprocess (the part that is ours).

Engine-agnostic process primitives: allocate a loopback port, spawn an OpenAI-compatible
server, wait for it to actually serve (TCP listening **then** a ``/v1/models`` response),
watch it for crashes, and stop it gracefully (SIGTERM → wait → SIGKILL). Each process's
stdout/stderr is captured to a log file so a failed startup can surface its tail.

Readiness rides the shared ``core.net.await_listening`` probe (TCP bind) plus a serving-
specific ``/v1/models`` HTTP check (it is actually serving, not merely bound).
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

import httpx

from core import net
from core.exceptions import ServingError

logger = logging.getLogger(__name__)

# on_crash(managed_id, returncode): the engine exited without a deliberate stop.
OnCrash = Callable[[str, int | None], Awaitable[None]]


class EngineExitedDuringStartup(ServingError):
    """The engine process exited before it began listening — a fast failure (a port
    already in use, an immediate crash). Distinct from a startup *timeout* so the caller
    can cheaply retry on a fresh port (closing the bind-to-0 → spawn race) without
    re-waiting the full timeout on a model that simply takes a long time to load.

    ``elapsed_s`` is how long the process lived. Only a *fast* exit looks like the port
    race worth retrying: an engine that ran for a minute and then died was loading a
    model, and re-running that load on a fresh port just pays the same failure again.
    """

    def __init__(self, message: str, elapsed_s: float = 0.0) -> None:
        super().__init__(message)
        self.elapsed_s = elapsed_s


@dataclass(frozen=True)
class ServeSpec:
    """How to launch an engine subprocess for one served model."""

    argv: list[str]
    env: dict[str, str] | None = None
    cwd: Path | None = None


@dataclass
class RunningProc:
    managed_id: str
    port: int
    pid: int
    base_url: str
    proc: asyncio.subprocess.Process
    log_fh: object  # an open binary file the process writes stdout/stderr to
    watchdog: asyncio.Task | None = None
    stopping: bool = False


class ProcessSupervisor:
    def __init__(
        self,
        *,
        startup_timeout_s: float = 180.0,
        stop_timeout_s: float = 10.0,
        poll_interval_s: float = 0.4,
    ) -> None:
        self._startup_timeout_s = startup_timeout_s
        self._stop_timeout_s = stop_timeout_s
        self._poll_interval_s = poll_interval_s
        self._procs: dict[str, RunningProc] = {}

    def allocate_port(self) -> int:
        """A free loopback TCP port (bind-to-0 then release — a small race the engine
        closes by binding immediately)."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    def is_running(self, managed_id: str) -> bool:
        proc = self._procs.get(managed_id)
        return bool(proc and proc.proc.returncode is None)

    async def spawn(
        self,
        managed_id: str,
        spec: ServeSpec,
        port: int,
        *,
        base_url: str,
        on_crash: OnCrash,
        log_path: Path,
        timeout_s: float | None = None,
    ) -> RunningProc:
        """Start the engine and return once it is actually serving. Raises
        ``ServingError`` (with the log tail) if it doesn't come up.

        ``timeout_s`` overrides the constructor default for this engine — how long
        "starting" may take is a property of the engine, not of the supervisor (one binds
        its port before loading weights, another loads them first)."""
        await self.stop(managed_id)  # clear any prior process for this model
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_fh = open(log_path, "ab")  # noqa: SIM115 — handle lives as long as the process
        try:
            proc = await asyncio.create_subprocess_exec(
                *spec.argv,
                stdout=log_fh,
                stderr=asyncio.subprocess.STDOUT,
                env=spec.env,
                cwd=str(spec.cwd) if spec.cwd else None,
            )
        except (OSError, ValueError) as exc:
            log_fh.close()
            raise ServingError(f"could not launch the engine: {exc}") from exc

        running = RunningProc(managed_id, port, proc.pid, base_url, proc, log_fh)
        self._procs[managed_id] = running
        try:
            await self._await_ready(port, base_url, proc, timeout_s or self._startup_timeout_s)
        except EngineExitedDuringStartup as exc:
            await self.stop(managed_id)
            tail = _read_tail(log_path)
            detail = f"{exc}" + (f"\n{tail}" if tail else "")
            # Carry the lifetime forward so the caller can tell a fast bind failure
            # (worth retrying on a fresh port) from a model that failed mid-load.
            raise EngineExitedDuringStartup(
                f"the engine failed to start: {detail}", exc.elapsed_s
            ) from exc
        except ServingError as exc:
            await self.stop(managed_id)
            tail = _read_tail(log_path)
            detail = f"{exc}" + (f"\n{tail}" if tail else "")
            raise ServingError(f"the engine failed to start: {detail}") from exc

        running.watchdog = asyncio.create_task(self._watch(running, on_crash))
        return running

    async def stop(self, managed_id: str) -> None:
        running = self._procs.pop(managed_id, None)
        if running is None:
            return
        running.stopping = True
        if running.watchdog is not None:
            running.watchdog.cancel()
            with suppress(asyncio.CancelledError):
                await running.watchdog
        proc = running.proc
        if proc.returncode is None:
            with suppress(ProcessLookupError):
                proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=self._stop_timeout_s)
            except TimeoutError:
                with suppress(ProcessLookupError):
                    proc.kill()
                with suppress(Exception):
                    await proc.wait()
        with suppress(Exception):
            running.log_fh.close()  # type: ignore[attr-defined]

    async def stop_all(self) -> None:
        for managed_id in list(self._procs):
            await self.stop(managed_id)

    def terminate_orphan(self, pid: int) -> None:
        """Best-effort SIGTERM to a pid recorded by a *prior* process — used at startup
        reconcile, where an engine outlived a backend crash and there's no handle to it.
        No SIGKILL escalation: the pid could have been recycled since, so it's never
        force-killed, and any error (already gone, not ours, no permission) is ignored."""
        with suppress(ProcessLookupError, PermissionError, OSError):
            os.kill(pid, signal.SIGTERM)

    async def _await_ready(
        self,
        port: int,
        base_url: str,
        proc: asyncio.subprocess.Process,
        timeout_s: float,
    ) -> None:
        loop = asyncio.get_running_loop()
        started = loop.time()
        deadline = started + timeout_s
        # 1) TCP: wait for the server to bind the port (failing fast if it exits first).
        try:
            await net.await_listening(
                port,
                max(0.0, deadline - loop.time()),
                poll_interval_s=self._poll_interval_s,
                is_alive=lambda: proc.returncode is None,
            )
        except ConnectionError:
            raise EngineExitedDuringStartup(
                "the engine process exited during startup", loop.time() - started
            ) from None
        except TimeoutError:
            raise ServingError(
                f"the engine did not start listening within {timeout_s:.0f}s"
            ) from None
        # 2) HTTP: wait for an OpenAI-compatible /v1/models response (it is serving,
        # not merely bound). 5xx is "not ready yet"; anything below is good enough.
        async with httpx.AsyncClient(timeout=5.0) as client:
            while True:
                if proc.returncode is not None:
                    raise EngineExitedDuringStartup(
                        "the engine process exited during startup", loop.time() - started
                    )
                try:
                    resp = await client.get(f"{base_url}/models")
                    if resp.status_code < 500:
                        return
                except httpx.HTTPError:
                    pass
                if loop.time() >= deadline:
                    raise ServingError("the engine did not become ready in time")
                await asyncio.sleep(self._poll_interval_s)

    async def _watch(self, running: RunningProc, on_crash: OnCrash) -> None:
        returncode = await running.proc.wait()
        if running.stopping:
            return
        self._procs.pop(running.managed_id, None)
        with suppress(Exception):
            running.log_fh.close()  # type: ignore[attr-defined]
        logger.warning(
            "serving: engine for %s exited unexpectedly (rc=%s)",
            running.managed_id,
            returncode,
        )
        with suppress(Exception):
            await on_crash(running.managed_id, returncode)


def _read_tail(path: Path, max_bytes: int = 2000) -> str:
    try:
        data = path.read_bytes()[-max_bytes:]
    except OSError:
        return ""
    return data.decode(errors="replace").strip()
