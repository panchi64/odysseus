"""The mechanics behind the code-mode shell: one persistent working directory, the
background processes started from it, and the fence every command is wrapped in.

**The behaviour is the harness `Shell`'s on purpose.** The model has been trained on those
four tools — their names, their arguments, the shape of what they return — and changing any
of it to gain a fence would cost more than the fence is worth. What is *not* the harness's
is the seam: it spawns processes itself, with nowhere to rewrite a command, and a code
conversation's shell has to run every command under OS confinement or not at all. So the
shape is copied and the spawn is ours. ``tools/shell.py`` keeps the model-facing contract;
what happens to a process is here.

The working directory persists between calls because a person's shell does, and because
the permission judge reads relative paths against it (``services/permissions/judge.py``).
It is captured out of band, into a temp file whose random name the agent's own command
cannot address: parsing a sentinel out of stdout would let any command that prints the
sentinel redirect where the next one runs.
"""

from __future__ import annotations

import asyncio
import errno
import functools
import os
import re
import shlex
import tempfile
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import IO, TYPE_CHECKING, Concatenate, Protocol

from pydantic_ai.exceptions import ModelRetry
from pydantic_ai_harness._output import truncate_tail
from pydantic_ai_harness.shell._capability import _DEFAULT_DENIED_COMMANDS

from .process import filtered_env, kill_tree, spawn_confined, terminate_tree

if TYPE_CHECKING:  # pragma: no cover — the fence's own type, never imported at runtime
    from sandbox_runtime import SandboxRuntimeConfig

#: Destructive programs (`rm`, `dd`, `mkfs`, `shutdown`, …) refused by name. Taken from the
#: harness rather than restated: it is a guardrail against a slip, not a boundary — the
#: fence is the boundary — and two copies of a guardrail is one copy that stops being
#: updated when the other grows an entry.
_DENIED_COMMANDS: frozenset[str] = frozenset(_DEFAULT_DENIED_COMMANDS)

#: Programs that want a terminal. Under this fence they would not fail — they would hang
#: until the timeout, spending the turn on nothing.
_INTERACTIVE = re.compile(
    r"^(vi|vim|nano|emacs|less|more|top|htop|man)\b|^sudo\s|^(passwd|ssh|telnet|ftp)\b"
)

# Spawning fails with `FileNotFoundError`/`NotADirectoryError` when the working directory
# is gone — which the model's own last command may well have deleted, and which it can fix.
# Every other errno (EMFILE, ENOMEM) is the host's, and must keep aborting the run rather
# than sending the model into a retry loop it cannot win.
_RECOVERABLE_ERRNOS: dict[int | None, str] = {
    errno.ENOENT: "The working directory no longer exists.",
    errno.ENOTDIR: "The working directory is no longer a directory.",
}


class Confiner(Protocol):
    """Rewrites a command so the OS holds it to ``profile``. A protocol rather than
    :func:`services.sandbox.fence.wrap` itself because a test driving the real fence would
    be testing seatbelt.

    The profile arrives per call and is built elsewhere (``services/sandbox/fence.py``,
    from the reach the model declared). Nothing in this module knows what a reach is: the
    shell runs a process under a boundary it is handed, and what that boundary should be is
    a permissions question answered one layer up in ``tools/shell.py``."""

    async def __call__(self, command: str, *, profile: SandboxRuntimeConfig) -> str: ...


def _recoverable[**P](
    fn: Callable[Concatenate[FencedShell, P], Awaitable[str]],
) -> Callable[Concatenate[FencedShell, P], Awaitable[str]]:
    """Turn what the model can correct into `ModelRetry`, and leave the rest alone.

    Pydantic AI feeds only `ModelRetry` back as a retry prompt; anything else aborts the
    whole run. A refused command and a working directory an earlier command destroyed are
    both the agent's to act on, so they go back to it rather than ending the turn."""

    @functools.wraps(fn)
    async def wrapper(self: FencedShell, *args: P.args, **kwargs: P.kwargs) -> str:
        try:
            return await fn(self, *args, **kwargs)
        except PermissionError as exc:
            raise ModelRetry(str(exc)) from exc
        except OSError as exc:
            reason = _RECOVERABLE_ERRNOS.get(exc.errno)
            if reason is None:
                raise
            # `str(exc)` embeds the absolute host path; the reason alone doesn't.
            raise ModelRetry(reason) from exc

    return wrapper


class _Background:
    """A process `start` left running, and the files its output accumulates in."""

    __slots__ = ("proc", "out_path", "err_path", "finished", "exit_code")

    def __init__(self, proc: asyncio.subprocess.Process, out_path: str, err_path: str) -> None:
        self.proc = proc
        self.out_path = out_path
        self.err_path = err_path
        self.finished = False
        self.exit_code: int | None = None


class FencedShell:
    """One workspace's shell: the drifting working directory, the background processes
    started in it, and the fence. Built per worktree and shared by the runs working there,
    so a `cd` and a dev server both outlive the turn that made them."""

    def __init__(
        self,
        root: Path,
        *,
        confiner: Confiner,
        default_timeout: float,
        max_output_chars: int,
    ) -> None:
        self._root = root
        self._cwd = root
        self._confine = confiner
        self._default_timeout = default_timeout
        self._max_output_chars = max_output_chars
        self._background: dict[str, _Background] = {}

    @property
    def cwd(self) -> Path:
        """The directory the next command will start in — the worktree root, or wherever
        inside it an earlier `cd` left the session."""
        return self._cwd

    @_recoverable
    async def run(
        self,
        command: str,
        *,
        profile: SandboxRuntimeConfig | None,
        timeout_seconds: float | None = None,
    ) -> str:
        """Run ``command`` to completion under ``profile`` and return its labelled output."""
        _check(command)
        timeout = timeout_seconds if timeout_seconds is not None else self._default_timeout
        wrapped, cwd_file = self._with_cwd_capture(command)
        out, err = _stream_files("run")
        try:
            proc = await self._spawn(wrapped, profile, out, err)
            out.close()
            err.close()
            try:
                await asyncio.wait_for(proc.wait(), timeout=timeout)
            except TimeoutError:
                await terminate_tree(proc)
                return self._capped(f"[Command timed out after {timeout}s]")
            except BaseException:
                # Cancellation lands here — the run hit its bound, or the operator pressed
                # Stop. Unwinding without reaping would leave a build, a test run or a
                # server the command started alive on the operator's machine, writing into
                # two files the `finally` below is about to unlink, with no run left to
                # stop it. Not awaited: this coroutine is already being torn down.
                kill_tree(proc)
                raise
            exit_code = proc.returncode or 0
            if exit_code == 0:
                self._apply_captured_cwd(cwd_file)
            output = _labelled(out.name, err.name) or "(no output)"
            return self._capped(
                output if exit_code == 0 else f"{output}\n[exit code: {exit_code}]"
            )
        finally:
            # The spawned process holds its own descriptors; ours are done with once it
            # has them, and a leaked pair per command would outlast the conversation.
            out.close()
            err.close()
            _unlink(out.name, err.name, str(cwd_file))

    @_recoverable
    async def start(self, command: str, *, profile: SandboxRuntimeConfig | None) -> str:
        """Start ``command`` in the background under ``profile``, and return its id."""
        _check(command)
        command_id = uuid.uuid4().hex[:12]
        out, err = _stream_files(command_id)
        try:
            proc = await self._spawn(command, profile, out, err)
        except BaseException:
            _unlink(out.name, err.name)
            raise
        finally:
            out.close()
            err.close()
        self._background[command_id] = _Background(proc, out.name, err.name)
        return self._capped(f"Started background command: {command!r}\nID: {command_id}")

    async def check(self, command_id: str) -> str:
        """How far a background command has got, and everything it has printed."""
        bg = self._background.get(command_id)
        if bg is None:
            return f"[Error: unknown command ID {command_id!r}]"
        if not bg.finished and bg.proc.returncode is not None:
            bg.exit_code = bg.proc.returncode
            bg.finished = True
        status = "finished" if bg.finished else "running"
        parts = [_labelled(bg.out_path, bg.err_path) or "(no output yet)", f"[status: {status}]"]
        if bg.finished and bg.exit_code is not None:
            parts.append(f"[exit code: {bg.exit_code}]")
        return self._capped("\n".join(parts))

    async def stop(self, command_id: str) -> str:
        """Stop a background command's whole group and hand back its final output.

        Asked to stop before it is made to: the agent is told to call this on everything
        it starts, so a server or a compose stack reaches it in the normal course of work
        and deserves the chance to shut itself down."""
        bg = self._background.pop(command_id, None)
        if bg is None:
            return f"[Error: unknown command ID {command_id!r}]"
        if not bg.finished:
            await terminate_tree(bg.proc)
            bg.exit_code = bg.proc.returncode
            bg.finished = True
        parts = [_labelled(bg.out_path, bg.err_path) or "(no output)", "[stopped]"]
        if bg.exit_code is not None:
            parts.append(f"[exit code: {bg.exit_code}]")
        _unlink(bg.out_path, bg.err_path)
        return self._capped("\n".join(parts))

    async def shutdown(self) -> None:
        """Stop everything still running here, for a shell whose workspace is going away.

        The agent is told to stop what it starts, and one that ran out of time or was
        cancelled never got there. A shell that outlives its turn can wait for that call;
        a delegated run's cannot — its ids lived only in a transcript that has ended, and
        its processes were started in sessions of their own, so nothing else reaps them.
        """
        for command_id in list(self._background):
            await self.stop(command_id)

    async def _spawn(
        self, command: str, profile: SandboxRuntimeConfig | None, out: IO[bytes], err: IO[bytes]
    ) -> asyncio.subprocess.Process:
        """Fence ``command``, then start it in the tracked directory with a filtered env.

        ``None`` runs it as written. That is not this module's decision and it is not a
        fallback: `tools/shell.py` returns no profile only where somebody's explicit yes
        asked for the unfenced machine, and a host with no fence at all refuses the tools
        outright long before anything reaches here. Applying a fence "just in case" would
        break the act that was approved; inventing one here would put the decision in two
        places.
        """
        fenced = command if profile is None else await self._confine(command, profile=profile)
        return await spawn_confined(
            fenced, cwd=self._cwd, env=filtered_env(), stdout=out, stderr=err
        )

    def _with_cwd_capture(self, command: str) -> tuple[str, Path]:
        """``command`` with its final directory recorded out of band (see the module
        docstring). Wrapped *before* the fence, so the capture happens inside it."""
        fd, name = tempfile.mkstemp(prefix="odysseus_cwd_")
        os.close(fd)
        wrapped = f"{command}\n__ody_ec=$?\npwd > {shlex.quote(name)}\nexit $__ody_ec"
        return wrapped, Path(name)

    def _apply_captured_cwd(self, cwd_file: Path) -> None:
        """Move the tracked directory to wherever the command ended up — **while that is
        still inside the worktree**.

        The containment is the load-bearing half. The permission layer measures every
        relative path a later command writes against the worktree root
        (``services/permissions/shell_ast.py``), so a `cd` that moved the tracked directory
        out of the worktree would leave every later containment claim measured against the
        wrong place: `cat secrets.txt` would clear as contained while reading some other
        directory's file. The fence would not catch it either — it bounds writes and egress,
        never reads.

        Both spellings of the root are compared, because the two ends disagree about it on
        macOS: the shell starts at the path it was given and `pwd` reports the one the
        kernel resolved, so `/tmp/wt` and `/private/tmp/wt` are one directory under two
        names and comparing against a single spelling would stop tracking `cd` entirely.

        The whole read is guarded, not only the open: the command it belongs to already
        succeeded, so a capture that is not UTF-8 or a path the OS refuses to stat is
        bookkeeping this can drop, not a tool failure to report."""
        try:
            recorded = cwd_file.read_text(encoding="utf-8").strip()
            if not recorded:
                return
            landed = Path(recorded)
            if landed.is_dir() and self._contains(landed):
                self._cwd = landed
        except (OSError, ValueError):
            return

    def _contains(self, candidate: Path) -> bool:
        """Whether ``candidate`` is the worktree root or something under it."""
        for root in (self._root, self._root.resolve()):
            if candidate == root or root in candidate.parents:
                return True
        return False

    def _capped(self, text: str) -> str:
        """Trimmed from the front — the exit code and the id line are at the tail."""
        return truncate_tail(text, self._max_output_chars)


def _check(command: str) -> None:
    """Refuse what this shell will not run at all, before anything is spawned. Best-effort,
    and not the boundary: a determined agent walks around a name check with an interpreter.
    The boundary is the fence every command is wrapped in."""
    if "\x00" in command:
        raise ModelRetry("The command contains a NUL byte, which cannot be passed to a process.")
    try:
        # `os.fsencode`, not `str.encode`: the spawn encodes with the filesystem encoding
        # and `surrogateescape`, so plain UTF-8 here would reject commands the OS runs.
        os.fsencode(command)
    except UnicodeEncodeError as exc:
        raise ModelRetry(
            "The command contains characters that cannot be encoded for the operating system."
        ) from exc
    if _INTERACTIVE.match(command.strip()):
        raise PermissionError(f"Interactive commands are not allowed. Command: {command!r}")
    try:
        tokens = shlex.split(command)
    except ValueError:
        return
    if tokens and tokens[0] in _DENIED_COMMANDS:
        raise PermissionError(f"Command {tokens[0]!r} is denied.")


def _stream_files(prefix: str) -> tuple[IO[bytes], IO[bytes]]:
    """Two temp files for one command's streams. Files rather than pipes, in the foreground
    too: a pipe has to be drained while the process runs or it fills and deadlocks, and the
    same buffers then serve `check` without a second mechanism for it."""
    return (
        tempfile.NamedTemporaryFile(mode="w+b", prefix=f"odysseus_{prefix}_out_", delete=False),
        tempfile.NamedTemporaryFile(mode="w+b", prefix=f"odysseus_{prefix}_err_", delete=False),
    )


def _labelled(out_path: str, err_path: str) -> str:
    """What the model sees: each stream named, empty ones left out entirely."""
    sections = [
        f"[{label}]\n{text}"
        for label, text in (("stdout", _read(out_path)), ("stderr", _read(err_path)))
        if text
    ]
    return "\n".join(sections)


def _read(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _unlink(*paths: str) -> None:
    for path in paths:
        try:
            os.unlink(path)
        except OSError:
            pass
