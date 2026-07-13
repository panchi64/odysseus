"""The Operator Shell — a host PTY streamed to the browser over a WebSocket.

Two pieces: a single-use, TTL-bounded **host-mode token** (minted only after a
fresh password check, spent exactly once by the WebSocket handshake) and the
**session** itself — a real login shell (`$SHELL`, falling back to `/bin/bash`)
spawned in its own PTY and process group, pumped byte-for-byte to/from the
socket. This module is never imported by `agent/`, `tools/`, or `research/` —
see `tests/test_shell_guard.py`, which asserts that invariant by grepping the
source tree, since a host shell reachable by the model would blow through every
sensitive-action approval gate at once.

The WebSocket upgrade bypasses the ASGI auth middleware entirely (it only
inspects `scope["type"] == "http"`), so `open_session` re-implements the full
auth chain itself: bearer session token, vault-unlocked, concurrent-session
limit, host-mode token — in that order (the session-limit check comes before
the token is spent, so a busy rejection never burns a still-valid token) —
each a distinct close code so the frontend can react precisely (re-login vs
re-unlock vs "busy" vs re-authenticate host mode).

A vault lock must kill every live session immediately (a locked vault means the
operator's key is gone from memory; leaving a root shell open past that point
defeats the point of locking). `kill_all` is registered with the vault as a
synchronous on-lock callback so this never depends on the auth route knowing
the shell exists.
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
import pty
import secrets
import signal
import struct
import subprocess
import termios
import time
from contextlib import suppress
from dataclasses import dataclass, field

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from core.auth import AuthManager
from core.config import Settings
from core.vault import Vault

logger = logging.getLogger(__name__)

# Bounds on the first-message auth handshake and on the PTY read chunk size —
# generous enough for a fast terminal paste without ever unbounding a read.
_AUTH_FRAME_TIMEOUT_S = 5.0
_READ_CHUNK = 65536
# Grace window between SIGHUP and the SIGKILL escalation when a session is torn
# down — long enough for a shell to unwind its own cleanup, short enough that
# a hung process never holds up a lock/disconnect/shutdown for long.
_KILL_GRACE_S = 0.5
_KILL_HARD_TIMEOUT_S = 1.0
_REAP_POLL_S = 0.05


@dataclass
class _Session:
    id: str
    websocket: WebSocket
    master_fd: int
    process: subprocess.Popen
    pgid: int
    terminate: asyncio.Event = field(default_factory=asyncio.Event)
    child_exited: asyncio.Event = field(default_factory=asyncio.Event)
    close_code: int = 1000
    exit_code: int = 0
    reaped: bool = False
    last_activity: float = field(default_factory=time.monotonic)
    fd_closed: bool = False


class ShellService:
    """Host-mode tokens + the live PTY session registry."""

    def __init__(self, settings: Settings, vault: Vault, auth_manager: AuthManager) -> None:
        self._settings = settings
        self._vault = vault
        self._auth_manager = auth_manager
        self._host_tokens: list[tuple[str, float]] = []  # (token, expires-at monotonic)
        self._sessions: dict[str, _Session] = {}

    # --- host-mode token store --------------------------------------------------

    def mint_host_token(self) -> tuple[str, float]:
        """Issue a fresh single-use host-mode token. Called only after the caller
        has already re-verified the operator's password (`routes/shell.py`)."""
        self._prune_host_tokens()
        ttl = self._settings.shell_host_token_ttl_s
        token = secrets.token_urlsafe(32)
        self._host_tokens.append((token, time.monotonic() + ttl))
        return token, ttl

    def consume_host_token(self, token: str) -> bool:
        """Spend a token: constant-time compare against every live candidate
        (mirrors `routes/tasks.py`'s webhook match, so a caller's timing can't
        narrow down a valid token), single-use, and TTL-bounded."""
        self._prune_host_tokens()
        if not token:
            return False
        matched = next(
            (
                candidate
                for candidate in self._host_tokens
                if secrets.compare_digest(candidate[0], token)
            ),
            None,
        )
        if matched is None:
            return False
        self._host_tokens.remove(matched)
        return True

    def _prune_host_tokens(self) -> None:
        now = time.monotonic()
        self._host_tokens = [(t, exp) for t, exp in self._host_tokens if exp > now]

    # --- session registry --------------------------------------------------------

    def can_open(self) -> bool:
        return len(self._sessions) < self._settings.shell_max_sessions

    def kill_all(self) -> None:
        """Synchronous — the vault's on-lock callback. Signals every live session's
        process group and flips its termination event; the async pump loops (already
        running) observe that event and close their own sockets. Deliberately never
        touches `master_fd` itself — `_pump`'s own reader is still registered on it
        at this point, so closing here would race `_pump`'s eventual
        `_kill_with_grace` close. The fd is single-owner: only `_close_master`
        (called after the reader is removed) ever closes it."""
        for session in list(self._sessions.values()):
            session.close_code = 4423
            with suppress(ProcessLookupError, OSError):
                os.killpg(session.pgid, signal.SIGHUP)
            session.terminate.set()

    @staticmethod
    def _close_master(session: _Session) -> None:
        """Idempotent, single-owner close of `master_fd` — safe to call from both
        `_kill_with_grace` and `stop()`'s force-kill branch even if the other
        already closed it (or will), since exactly one call ever actually closes
        the fd. Callers must remove the event-loop reader before calling this."""
        if session.fd_closed:
            return
        session.fd_closed = True
        with suppress(OSError):
            os.close(session.master_fd)

    async def stop(self) -> None:
        """App shutdown: terminate and fully clean up every live session."""
        for session in list(self._sessions.values()):
            session.close_code = 1000
            with suppress(ProcessLookupError, OSError):
                os.killpg(session.pgid, signal.SIGHUP)
            session.terminate.set()
        for _ in range(40):
            if not self._sessions:
                return
            await asyncio.sleep(_REAP_POLL_S)
        # A pump task that never got scheduled before shutdown (e.g. the loop is
        # being torn down without another yield) is force-killed directly so no
        # PTY child is orphaned past process exit.
        for session in list(self._sessions.values()):
            with suppress(ProcessLookupError, OSError):
                os.killpg(session.pgid, signal.SIGKILL)
            self._close_master(session)
            self._sessions.pop(session.id, None)

    # --- the socket lifecycle -----------------------------------------------------

    async def open_session(self, websocket: WebSocket) -> None:
        """The full first-message-auth handshake, then the PTY session, per the
        wire contract. Never raises past acceptance — every failure closes the
        socket with the contract's code instead."""
        await websocket.accept()

        try:
            raw = await asyncio.wait_for(
                websocket.receive_text(), timeout=_AUTH_FRAME_TIMEOUT_S
            )
        except TimeoutError:
            await self._safe_close(websocket, 4408)
            return
        except WebSocketDisconnect:
            return

        frame = self._parse_auth_frame(raw)
        if frame is None:
            await self._safe_close(websocket, 4401)
            return
        bearer, host_token = frame

        if self._settings.auth_enabled and not self._auth_manager.verify(bearer):
            await self._safe_close(websocket, 4401)
            return
        if not self._vault.is_unlocked:
            await self._safe_close(websocket, 4423)
            return
        # Checked before the token is spent: a busy rejection must leave a
        # still-valid host-mode token unspent so the client can retry it.
        if not self.can_open():
            await self._safe_close(websocket, 4409)
            return
        if not self.consume_host_token(host_token):
            await self._safe_close(websocket, 4403)
            return

        try:
            session = self._spawn_session(websocket)
        except OSError:
            logger.exception("shell: failed to spawn a PTY session")
            await self._safe_close(websocket, 1011)
            return

        self._sessions[session.id] = session
        try:
            await websocket.send_json({"type": "ready"})
            await self._pump(session)
        finally:
            self._sessions.pop(session.id, None)

    @staticmethod
    def _parse_auth_frame(raw: str) -> tuple[str, str] | None:
        try:
            frame = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(frame, dict) or frame.get("type") != "auth":
            return None
        bearer, host = frame.get("bearer"), frame.get("host")
        if not isinstance(bearer, str) or not isinstance(host, str):
            return None
        return bearer, host

    # --- PTY plumbing --------------------------------------------------------------

    def _spawn_session(self, websocket: WebSocket) -> _Session:
        preferred = os.environ.get("SHELL") or "/bin/zsh"
        candidates = (preferred,) if preferred == "/bin/bash" else (preferred, "/bin/bash")
        for shell in candidates:
            master_fd, slave_fd = pty.openpty()
            try:
                process = subprocess.Popen(
                    [shell],
                    stdin=slave_fd,
                    stdout=slave_fd,
                    stderr=slave_fd,
                    preexec_fn=os.setsid,
                    env=os.environ.copy(),
                    cwd=os.path.expanduser("~"),
                    close_fds=True,
                )
            except FileNotFoundError:
                os.close(master_fd)
                os.close(slave_fd)
                continue
            except BaseException:
                # Any other Popen failure (permissions, fd/proc exhaustion, …)
                # must not leak the pair we just opened before it propagates.
                os.close(master_fd)
                os.close(slave_fd)
                raise
            os.close(slave_fd)  # only the child needs the slave end now
            return _Session(
                id=secrets.token_urlsafe(16),
                websocket=websocket,
                master_fd=master_fd,
                process=process,
                pgid=process.pid,  # os.setsid makes the child its own group leader
            )
        raise OSError(f"no usable login shell found (tried {', '.join(candidates)})")

    async def _pump(self, session: _Session) -> None:
        """Drive one session to completion: pump PTY output out, client input in,
        watch for the child exiting / an idle timeout / an external termination
        (kill_all/stop), then clean up and close the socket per the contract."""
        loop = asyncio.get_running_loop()
        out_queue: asyncio.Queue[bytes | None] = asyncio.Queue()

        def _on_readable() -> None:
            try:
                data = os.read(session.master_fd, _READ_CHUNK)
            except OSError:
                data = b""
            if not data:
                with suppress(ValueError, OSError):
                    loop.remove_reader(session.master_fd)
                if not session.reaped:
                    with suppress(ChildProcessError):
                        pid, status = os.waitpid(session.process.pid, os.WNOHANG)
                        if pid:
                            session.exit_code = os.waitstatus_to_exitcode(status)
                            session.reaped = True
                session.child_exited.set()
                out_queue.put_nowait(None)
                return
            out_queue.put_nowait(data)

        loop.add_reader(session.master_fd, _on_readable)

        sender_task = asyncio.create_task(self._sender_loop(session.websocket, out_queue))
        receiver_task = asyncio.create_task(self._receiver_loop(session))
        idle_task = asyncio.create_task(self._idle_watcher(session))
        child_exited_task = asyncio.create_task(session.child_exited.wait())
        terminate_task = asyncio.create_task(session.terminate.wait())
        watch = {receiver_task, child_exited_task, terminate_task}

        try:
            done, _pending = await asyncio.wait(watch, return_when=asyncio.FIRST_COMPLETED)
        finally:
            with suppress(ValueError, OSError):
                loop.remove_reader(session.master_fd)

        for task in (receiver_task, child_exited_task, terminate_task, idle_task):
            if not task.done():
                task.cancel()
        out_queue.put_nowait(None)  # unstick the sender regardless of which path below runs

        if terminate_task in done:
            # An external termination (vault lock / idle timeout / shutdown) always
            # wins even if the child also happened to exit around the same time —
            # the socket closes with the reason code, no exit frame.
            await self._safe_close(session.websocket, session.close_code)
        elif child_exited_task in done:
            with suppress(Exception):
                await sender_task
            await self._safe_send_json(
                session.websocket, {"type": "exit", "code": session.exit_code}
            )
            await self._safe_close(session.websocket, 1000)
        # else: the client disconnected on its own — nothing left to send.

        await self._kill_with_grace(session)
        await asyncio.gather(
            sender_task, receiver_task, idle_task, child_exited_task, terminate_task,
            return_exceptions=True,
        )

    async def _sender_loop(
        self, websocket: WebSocket, queue: asyncio.Queue[bytes | None]
    ) -> None:
        """Drains PTY output onto the socket, preserving order — the single writer
        for binary frames, so the exit-frame send in `_pump` never races it."""
        while True:
            chunk = await queue.get()
            if chunk is None:
                return
            try:
                await websocket.send_bytes(chunk)
            except Exception:  # noqa: BLE001 — a dead socket just ends the pump
                return

    async def _receiver_loop(self, session: _Session) -> None:
        websocket = session.websocket
        while True:
            try:
                raw = await websocket.receive_text()
            except WebSocketDisconnect:
                return
            except Exception:  # noqa: BLE001 — any other socket failure ends the pump
                return
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(msg, dict):
                continue
            mtype = msg.get("type")
            if mtype == "stdin":
                data = msg.get("data")
                if not isinstance(data, str):
                    continue
                session.last_activity = time.monotonic()
                try:
                    os.write(session.master_fd, data.encode())
                except OSError:
                    return
            elif mtype == "resize":
                cols, rows = msg.get("cols"), msg.get("rows")
                if not isinstance(cols, int) or not isinstance(rows, int):
                    continue
                with suppress(OSError):
                    fcntl.ioctl(
                        session.master_fd,
                        termios.TIOCSWINSZ,
                        struct.pack("HHHH", rows, cols, 0, 0),
                    )

    async def _idle_watcher(self, session: _Session) -> None:
        timeout = self._settings.shell_idle_timeout_s
        if timeout <= 0:
            return
        while True:
            await asyncio.sleep(timeout)
            if time.monotonic() - session.last_activity >= timeout:
                session.close_code = 4403  # re-prompt host mode, like an expired grant
                session.terminate.set()
                return

    async def _kill_with_grace(self, session: _Session) -> None:
        """SIGHUP, then SIGKILL after a short grace if the process group is still
        alive; always ends with the master fd closed. Idempotent — safe even when
        `kill_all` already signalled/closed this session."""
        with suppress(ProcessLookupError, OSError):
            os.killpg(session.pgid, signal.SIGHUP)
        if not await self._wait_exit(session, timeout_s=_KILL_GRACE_S):
            with suppress(ProcessLookupError, OSError):
                os.killpg(session.pgid, signal.SIGKILL)
            await self._wait_exit(session, timeout_s=_KILL_HARD_TIMEOUT_S)
        self._close_master(session)

    @staticmethod
    async def _wait_exit(session: _Session, *, timeout_s: float) -> bool:
        """Poll (non-blocking) for the child to be reaped — never blocks the event
        loop on a hung ``waitpid``."""
        if session.reaped:
            return True
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                pid, status = os.waitpid(session.process.pid, os.WNOHANG)
            except ChildProcessError:
                session.reaped = True
                return True
            if pid:
                session.exit_code = os.waitstatus_to_exitcode(status)
                session.reaped = True
                return True
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(_REAP_POLL_S)

    @staticmethod
    async def _safe_close(websocket: WebSocket, code: int) -> None:
        with suppress(Exception):
            await websocket.close(code=code)

    @staticmethod
    async def _safe_send_json(websocket: WebSocket, payload: dict) -> None:
        with suppress(Exception):
            await websocket.send_json(payload)
