"""Preview tools — the agent surfaces its work for the operator to see.

Two shapes, both thin adapters over ``services/``:

- ``preview_publish_artifact`` captures a *file* the agent produced into the
  encrypted artifact store and emits ``artifact.published`` — a static snapshot.
- ``preview_start`` / ``preview_stop`` run a *live server* in the sandbox and
  emit ``preview.ready`` / ``preview.stopped`` — the backend reverse-proxies it
  to a sandboxed iframe. The session manager owns the container lifecycle.

If the sandbox or artifact store isn't wired into the run, the tools say so
rather than failing — the model adapts (graceful degradation).
"""

from __future__ import annotations

from pydantic_ai import FunctionToolset, RunContext

from runs import ArtifactPublished, PreviewReady, PreviewStopped
from services.artifacts import format_publish_result
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
        key = ctx.deps.sandbox_key
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
                conversation_id=view.conversation_id,
                title=view.title,
                filename=view.filename,
                content_type=view.content_type,
                kind=view.kind,
            )
        )
        return format_publish_result(view)

    @toolset.tool
    async def start(
        ctx: RunContext[RunDeps],
        command: list[str],
        port: int,
        title: str | None = None,
    ) -> str:
        """Run a live server in the sandbox and show it to the operator as an
        interactive preview — a web app, a dev server, a served site. ``command``
        is the argv that starts the server (e.g. ``["python", "-m", "http.server",
        "8000"]`` or ``["npm", "run", "dev"]``); ``port`` is the port it listens on
        inside the sandbox. The server must bind ``0.0.0.0`` (not ``127.0.0.1``) so
        it is reachable, and serve assets with relative URLs. Replaces any preview
        already running in this conversation. Returns once the server is up."""
        sessions = ctx.deps.sandbox_sessions
        if sessions is None:
            return "Live preview is unavailable (no sandbox runtime)."
        try:
            handle = await sessions.start_preview(ctx.deps.sandbox_key, command, port)
        except SandboxError as exc:
            return f"The preview server did not start: {exc}"
        ctx.deps.run.emit(
            PreviewReady(
                conversation_id=ctx.deps.sandbox_key,
                url=handle.path,
                title=title,
                command=" ".join(handle.command),
                port=port,
            )
        )
        return f"Live preview running at {handle.path} (serving '{' '.join(handle.command)}')."

    @toolset.tool
    async def stop(ctx: RunContext[RunDeps]) -> str:
        """Stop the live preview server running in this conversation, if any."""
        sessions = ctx.deps.sandbox_sessions
        if sessions is None:
            return "Live preview is unavailable (no sandbox runtime)."
        await sessions.stop_preview(ctx.deps.sandbox_key)
        ctx.deps.run.emit(PreviewStopped(conversation_id=ctx.deps.sandbox_key))
        return "Stopped the live preview."

    return toolset
