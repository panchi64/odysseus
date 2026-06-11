"""Code & shell tools — the agent's two execution paths, cleanly split.

``execute_code`` is the default: it runs in the host-isolated sandbox, so it is
**not** approval-gated — being contained, it carries no host-level risk and the
agent computes freely. ``run_host_command`` is the deliberate exception: it runs
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

from services.sandbox import SandboxError, SandboxSpec, run_on_host

from .deps import RunDeps

# language → the argv that runs source passed on the command line, inside the box.
_INTERPRETERS: dict[str, list[str]] = {
    "python": ["python", "-c"],
    "bash": ["bash", "-c"],
}


def code_toolset() -> FunctionToolset[RunDeps]:
    toolset: FunctionToolset[RunDeps] = FunctionToolset()

    @toolset.tool
    async def execute_code(
        ctx: RunContext[RunDeps],
        language: Literal["python", "bash"],
        code: str,
        stdin: str | None = None,
        network: bool = False,
        timeout_s: float = 30.0,
    ) -> dict:
        """Run code or a shell script in an isolated Linux sandbox, cut off from
        the host. The environment is a small Debian userland with ``python`` and
        ``bash`` on the path. Network egress is **off** unless you set
        ``network=True`` — do so when you need to fetch packages or data. The root
        filesystem is read-only; only the current working directory is writable.

        The sandbox **persists across calls in this conversation**: files you write
        and dependencies you install stay available for follow-up calls, so you can
        run something, see an error, fix it, and re-run without starting over. It is
        reclaimed after a stretch of inactivity (your files are kept and restored;
        installed packages may need reinstalling). Use this for computation,
        scripting, and iterating toward a working result."""
        sessions = ctx.deps.sandbox_sessions
        if sessions is None:
            return {
                "error": "Code execution is unavailable: no sandbox runtime is "
                "configured. Computation that would require running code cannot "
                "be done, and will not run on the host."
            }
        spec = SandboxSpec(
            command=[*_INTERPRETERS[language], code],
            stdin=stdin,
            network=network,
            timeout_s=timeout_s,
        )
        try:
            session = await sessions.acquire(ctx.deps.conversation_id or ctx.deps.run.id)
            result = await session.run(spec)
        except SandboxError as exc:
            return {"error": f"Sandbox failed to run: {exc}"}
        return {
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "timed_out": result.timed_out,
        }

    @toolset.tool(requires_approval=True)
    async def run_host_command(
        ctx: RunContext[RunDeps],
        command: str,
        explanation: str,
        timeout_s: float = 120.0,
    ) -> dict:
        """Run a command directly on the operator's host machine (NOT sandboxed).

        Only for when the host itself must change. ``explanation`` MUST be a
        plain-language description of what the command does and its effect on the
        host — it is shown to the operator for approval. Prefer ``execute_code``
        for anything that does not need the real host.
        """
        result = await run_on_host(command, timeout_s=timeout_s)
        return {
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "timed_out": result.timed_out,
        }

    return toolset
