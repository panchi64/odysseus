"""Preview tool — the agent surfaces a sandbox file for the operator to see.

A thin adapter: it reads a file the agent produced in its sandbox workspace,
hands the bytes to the artifact store (captured, encrypted at rest, decoupled
from the sandbox's lifecycle), and emits ``artifact.published`` so the UI can
render it. No logic here — capture and serving live in ``services/artifacts``.

If the sandbox or artifact store isn't wired into the run, it says so rather than
failing — the model adapts (graceful degradation).
"""

from __future__ import annotations

from pydantic_ai import FunctionToolset, RunContext

from runs import ArtifactPublished
from services.sandbox import SandboxError

from .deps import RunDeps


def preview_toolset() -> FunctionToolset[RunDeps]:
    toolset: FunctionToolset[RunDeps] = FunctionToolset()

    @toolset.tool
    async def publish_artifact(
        ctx: RunContext[RunDeps], path: str, title: str | None = None
    ) -> str:
        """Show a file you created in the sandbox to the operator as a preview — an
        HTML page, an image or chart, a code snippet. ``path`` is the file's path
        within the sandbox working directory. Use this to surface a result for
        viewing, not to store data."""
        sessions = ctx.deps.sandbox_sessions
        store = ctx.deps.artifacts
        if sessions is None or store is None:
            return "Preview is unavailable."
        key = ctx.deps.conversation_id or ctx.deps.run.id
        try:
            session = await sessions.acquire(key)
            content = session.read_file(path)
        except SandboxError as exc:
            return f"Could not read {path!r}: {exc}"
        view = await store.publish(
            ctx.deps.owner_id,
            key,
            filename=path.rsplit("/", 1)[-1],
            content=content,
            title=title,
            run_id=ctx.deps.run.id,
        )
        ctx.deps.run.emit(
            ArtifactPublished(
                artifact_id=view.id,
                title=view.title,
                filename=view.filename,
                content_type=view.content_type,
                kind=view.kind,
            )
        )
        return f"Published '{view.title}' as a {view.kind} preview (id {view.id})."

    return toolset
