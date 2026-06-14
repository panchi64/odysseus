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

from runs import ToolProgress
from services.sandbox import HostExecutionError, SandboxError, SandboxSpec, run_on_host

from .deps import RunDeps

# language → the argv that runs source passed on the command line, inside the box.
_INTERPRETERS: dict[str, list[str]] = {
    "python": ["python", "-c"],
    "bash": ["bash", "-c"],
}


def _failure_hint(exit_code: int, timed_out: bool) -> str:
    """A short, plain reason for a failed run — stderr is often empty for these."""
    if timed_out:
        return "It exceeded the time limit and was killed; reduce the work or raise timeout_s."
    if exit_code in (137, 139):  # SIGKILL / SIGSEGV
        return (
            f"The process was killed (exit {exit_code}) — often an out-of-memory "
            "kill, possibly a forced stop; check the work's memory use."
        )
    return f"It exited with a non-zero status ({exit_code}); see stderr for the error."


def _exec_result(result) -> dict:
    """Shape an execution result for the model, with an explicit success flag and,
    on failure, a legible hint alongside the raw streams so it can correct."""
    payload = {
        "ok": result.ok,
        "exit_code": result.exit_code,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "timed_out": result.timed_out,
    }
    if not result.ok:
        payload["error"] = _failure_hint(result.exit_code, result.timed_out)
    return payload


def code_toolset() -> FunctionToolset[RunDeps]:
    toolset: FunctionToolset[RunDeps] = FunctionToolset()

    @toolset.tool
    async def execute(
        ctx: RunContext[RunDeps],
        language: Literal["python", "bash"],
        code: str,
        stdin: str | None = None,
        network: bool = False,
        timeout_s: float = 30.0,
    ) -> dict:
        """Run ``python`` or a ``bash`` script on your own computer — a private
        Linux machine that is yours alone (it is not the operator's host). It runs a
        Debian userland with ``python``, ``bash``, and the usual command-line tools
        on the path.

        Your home and working directory is ``/work`` (where your shell starts). It
        is writable and persists across calls in this conversation: files you write
        and packages you install stay there, so you can run something, hit an error,
        fix it, and re-run without starting over. The rest of the filesystem is
        read-only, and ``/tmp`` is small and temporary — keep anything that matters
        in your working directory. After a long stretch of inactivity the machine is
        reclaimed: your files are kept and restored, but installed packages may need
        reinstalling.

        There is no internet unless you set ``network=True`` — do so to fetch
        packages or data. Install packages the normal way (``pip install <pkg>``
        with ``network=True``); they land in your working directory and import on
        later calls without needing the network again. Use it freely for
        computation, scripting, and iterating toward a working result.

        The result has ``ok``, ``exit_code``, ``stdout``, ``stderr``, and
        ``timed_out``; on failure it adds a short ``error`` hint. When it fails,
        read ``stderr`` for the cause, fix the code, and run again."""
        sessions = ctx.deps.sandbox_sessions
        if sessions is None:
            return {
                "ok": False,
                "error": "Code execution is unavailable: no sandbox runtime is "
                "configured. Computation that would require running code cannot "
                "be done, and will not run on the host.",
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
            # spins a fresh throwaway container, so it's a cold start too.
            if ctx.tool_call_id and (spec.network or not session.is_warm):
                ctx.deps.run.emit(
                    ToolProgress(
                        tool_call_id=ctx.tool_call_id,
                        partial="Starting the sandbox environment…",
                    )
                )
            result = await session.run(spec)
        except SandboxError as exc:
            # Any sandbox/infra failure comes back as something the model can act
            # on — it never escapes to crash the run.
            return {"ok": False, "error": f"The sandbox could not run the code: {exc}"}
        return _exec_result(result)

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
        return _exec_result(result)

    return toolset
