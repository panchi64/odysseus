"""Code & shell tools — the agent's two execution paths, cleanly split.

``code_execute`` is the default: it runs in the host-isolated sandbox, so it is
**not** approval-gated — being contained, it carries no host-level risk and the
agent computes freely. ``code_run_host_command`` is the deliberate exception: it runs
on the real host, so it is an approval-gated tool whose request must carry a
plain-language ``explanation`` the operator can judge without reading the command.

Both stay thin — the execution mechanics live in ``services/sandbox`` (the
sandboxed path and the host escape hatch). When no sandbox runtime is available
the sandboxed tool reports the capability is disabled and the model adapts; it
never silently falls back to the host.
"""

from __future__ import annotations

from typing import Literal

from pydantic_ai import FunctionToolset, RunContext

from core.config import Settings, get_settings
from core.text import truncate_middle
from runs import ToolProgress
from services.sandbox import HostExecutionError, SandboxError, SandboxSpec, run_on_host

from .deps import RunDeps

# language → the argv that runs source passed on the command line, inside the box.
_INTERPRETERS: dict[str, list[str]] = {
    "python": ["python", "-c"],
    "bash": ["bash", "-c"],
}

# Hitting the pids-limit surfaces as a failed fork/thread-create *inside* the process —
# unlike the OOM killer, there is no distinct container-level signal for it, so this is
# a crude heuristic over the OS errors that failure mode typically prints.
_PID_CAP_MARKERS = (
    "resource temporarily unavailable",
    "cannot allocate memory",
    "can't fork",
    "fork failed",
)


def _looks_like_pid_cap(stderr: str) -> bool:
    low = stderr.lower()
    return "fork" in low and any(marker in low for marker in _PID_CAP_MARKERS)


def _failure_hint(
    exit_code: int, timed_out: bool, stderr: str, *, memory: str, pids_limit: int
) -> str:
    """A short, plain reason for a failed run, naming the actual configured cap that
    was most likely hit — stderr is often empty for a hard kill, so being precise
    matters more here than for an ordinary non-zero exit."""
    if timed_out:
        return "It exceeded the time limit and was killed; reduce the work or raise timeout_s."
    if exit_code == 137:  # SIGKILL
        return (
            f"The process was killed (exit 137, SIGKILL) — most likely the "
            f"{memory} memory cap was hit; reduce memory use or process data in "
            "smaller chunks."
        )
    if exit_code == 139:  # SIGSEGV
        return (
            "The process crashed (exit 139, SIGSEGV) — a fault in the code itself, "
            "not a resource cap."
        )
    if _looks_like_pid_cap(stderr):
        return (
            f"The process could not create more processes/threads (capped at "
            f"{pids_limit}); reduce concurrency (fewer workers/threads/subprocesses)."
        )
    return f"It exited with a non-zero status ({exit_code}); see stderr for the error."


def _cap_stream(text: str, max_chars: int, *, sandboxed: bool) -> str:
    """Cap one stdout/stderr stream to ``max_chars``, eliding the middle (keeping the
    head and tail — errors and final state usually live at the tail) with an explicit
    inline marker stating how much was elided and where the full output still lives."""
    head, tail, elided = truncate_middle(text, max_chars)
    if not elided:
        return head
    redo = (
        "rerun piping it to a file under /work and read that file back in slices"
        if sandboxed
        else "rerun redirecting it to a file and read that file back in slices"
    )
    return (
        f"{head}\n"
        f"[… {elided:,} characters elided (kept the first {len(head):,} and last "
        f"{len(tail):,}); the full output was not kept — {redo}.]\n"
        f"{tail}"
    )


def _exec_result(result, settings: Settings, *, sandboxed: bool) -> dict:
    """Shape an execution result for the model: an explicit success flag, stdout/stderr
    each capped to half of ``settings.sandbox_output_max_chars`` (see `_cap_stream`), and
    on failure a legible hint naming which configured cap was likely hit."""
    per_stream_cap = settings.sandbox_output_max_chars // 2
    payload = {
        "ok": result.ok,
        "exit_code": result.exit_code,
        "stdout": _cap_stream(result.stdout, per_stream_cap, sandboxed=sandboxed),
        "stderr": _cap_stream(result.stderr, per_stream_cap, sandboxed=sandboxed),
        "timed_out": result.timed_out,
    }
    if not result.ok:
        payload["error"] = _failure_hint(
            result.exit_code,
            result.timed_out,
            result.stderr,
            memory=settings.sandbox_memory,
            pids_limit=settings.sandbox_pids_limit,
        )
    return payload


def _execute_description(settings: Settings) -> str:
    """The `execute` tool's description, generated fresh per toolset build (an
    explicit `description=` override — see `FunctionToolset.tool`) so it always states
    the sandbox's *actual* configured resource caps rather than a guess the model has
    no way to verify, and is precise enough to self-diagnose a 137/pid-cap failure."""
    per_stream_cap = settings.sandbox_output_max_chars // 2
    return (
        "Run `python` or a `bash` script on your own computer — a private Linux "
        "machine that is yours alone (it is not the operator's host). It runs a "
        "Debian userland with `python`, `bash`, and the usual command-line tools on "
        "the path.\n\n"
        "Your working directory is `/work` (where your shell starts). It is writable "
        "and persists across calls in this conversation: files you write and packages "
        "you install stay there, so you can run something, hit an error, fix it, and "
        "re-run without starting over. The rest of the filesystem is read-only, and "
        "`/tmp` is small and temporary — keep anything that matters in your working "
        "directory. After a long stretch of inactivity the machine is reclaimed: your "
        "files are kept and restored, but installed packages may need reinstalling.\n\n"
        "There is no internet unless you set `network=True` — do so to fetch "
        "packages or data. Install packages the normal way (`pip install <pkg>` with "
        "`network=True`); they land in your working directory and import on later "
        "calls without needing the network again. Use it freely for computation, "
        "scripting, and iterating toward a working result.\n\n"
        f"It is capped at {settings.sandbox_memory} memory, {settings.sandbox_cpus} "
        f"CPU, and {settings.sandbox_pids_limit} processes/threads — exceeding memory "
        "gets the run killed, exceeding the CPU cap only throttles it (the run keeps "
        "going, just slower, and may then also hit the timeout), and exceeding the "
        "process cap fails the next fork/thread-create inside the run. `stdout`/"
        f"`stderr` are each capped to {per_stream_cap:,} characters; a stream over "
        "that has its middle elided (the head and tail are kept, since errors live "
        "at the tail) — for large output, redirect it to a file under `/work` and "
        "read that file back in slices instead of printing it all.\n\n"
        "The result has `ok`, `exit_code`, `stdout`, `stderr`, and `timed_out`; on "
        "failure it adds a short `error` hint naming which cap (if any) was likely "
        "hit. When it fails, read `stderr` for the cause, fix the code, and run "
        "again."
    )


def code_toolset() -> FunctionToolset[RunDeps]:
    # Read once per toolset build (this factory runs fresh per turn, see
    # `tools/toolsets.py`) so the `execute` description below states the sandbox's
    # actual configured caps, not a value baked in at import time.
    settings = get_settings()
    toolset: FunctionToolset[RunDeps] = FunctionToolset()

    @toolset.tool(description=_execute_description(settings))
    async def execute(
        ctx: RunContext[RunDeps],
        language: Literal["python", "bash"],
        code: str,
        stdin: str | None = None,
        network: bool = False,
        timeout_s: float = 30.0,
    ) -> dict:
        # The model-facing description is generated by `_execute_description` above
        # (registered via `description=`) so it can interpolate the live config caps —
        # a plain docstring can't. Keep this in sync when the shape changes.
        sessions = ctx.deps.sandbox_sessions
        if sessions is None:
            return {
                "ok": False,
                "error": "Your computer is unavailable right now: no runtime is "
                "configured. Computation that would require running code cannot "
                "be done, and will not run on the operator's host.",
            }
        spec = SandboxSpec(
            command=[*_INTERPRETERS[language], code],
            stdin=stdin,
            network=network,
            timeout_s=timeout_s,
        )
        try:
            session = await sessions.acquire(ctx.deps.sandbox_key)
            # A cold container takes a beat to spin up — longer still the first
            # time, when the image must be pulled. Announce that wait so the run
            # reads as the environment starting, not the model stalling; a warm
            # session runs at once and needs no notice. A network call always
            # spins a fresh throwaway container, so it's a cold start too. When
            # the boot-time image pull is still in flight, say so truthfully
            # (a minutes-long download reads very differently from an ordinary
            # few-hundred-ms container start).
            if ctx.tool_call_id and (spec.network or not session.is_warm):
                downloading = getattr(sessions, "image_warmup_pending", False)
                partial = (
                    "Downloading the sandbox image, this first run can take a "
                    "few minutes…"
                    if downloading
                    else "Starting the sandbox environment…"
                )
                ctx.deps.run.emit(
                    ToolProgress(tool_call_id=ctx.tool_call_id, partial=partial)
                )
            result = await session.run(spec)
        except SandboxError as exc:
            # Any sandbox/infra failure comes back as something the model can act
            # on — it never escapes to crash the run.
            return {"ok": False, "error": f"Your computer could not run the code: {exc}"}
        return _exec_result(result, settings, sandboxed=True)

    @toolset.tool(requires_approval=True)
    async def run_host_command(
        ctx: RunContext[RunDeps],
        command: str,
        explanation: str,
        timeout_s: float = 120.0,
    ) -> dict:
        """Run a command directly on the operator's host machine — their real
        computer, not your own.

        Only for when the host itself must change. ``explanation`` MUST be a
        plain-language description of what the command does and its effect on the
        host — it is shown to the operator for approval. Prefer ``code_execute``
        for anything that does not need the real host.
        """
        try:
            result = await run_on_host(command, timeout_s=timeout_s)
        except HostExecutionError as exc:
            return {"ok": False, "error": f"The host command could not be launched: {exc}"}
        return _exec_result(result, settings, sandboxed=False)

    return toolset
