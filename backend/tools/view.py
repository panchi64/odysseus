"""View tools — the agent shows the operator what it built, in one versioned View.

A conversation has a single **View**: a canvas beside the chat that holds a live,
interactive **head** plus a history of snapshot **versions** to compare against.
Two mechanisms behind one capability, both thin adapters over ``services/``:

- a **static version** captures a file the agent produced (encrypted at rest) and
  emits ``view.version`` — a durable, comparable snapshot.
- a **live head** runs a server in the sandbox and emits ``view.live`` — the
  backend reverse-proxies it into a sandboxed iframe.

Artifacts and live previews used to be two separate tools/products; that split was
a mechanism (a frozen file vs. a running process) leaking out. Here they are the
*history* and the *head* of one View, reached through one ``view`` tool.

If the sandbox or the version store isn't wired into the run, the tool says so
rather than failing — the model adapts (graceful degradation).
"""

from __future__ import annotations

from pydantic_ai import FunctionToolset, ModelRetry, RunContext

from runs import ViewLive, ViewLiveStopped, ViewVersion
from services.artifacts import format_publish_result
from services.sandbox import SandboxError

from .deps import RunDeps


async def _show_file(ctx: RunContext[RunDeps], file: str, title: str | None) -> str:
    """Capture a file the agent produced as a new static version of the View."""
    sessions = ctx.deps.sandbox_sessions
    store = ctx.deps.artifacts
    if sessions is None or store is None:
        return "The view is unavailable."
    try:
        session = await sessions.acquire(ctx.deps.sandbox_key)
        content = session.read_file(file)
    except SandboxError as exc:
        return f"Could not read {file!r}: {exc}"
    view = await store.publish(
        ctx.deps.owner_id,
        ctx.deps.sandbox_key,
        filename=file.rsplit("/", 1)[-1],
        content=content,
        title=title,
        run_id=ctx.deps.run.id,
    )
    ctx.deps.run.emit(
        ViewVersion(
            conversation_id=view.conversation_id,
            version_id=view.id,
            title=view.title,
            filename=view.filename,
            content_type=view.content_type,
            kind=view.kind,
        )
    )
    return format_publish_result(view)


async def _show_live(
    ctx: RunContext[RunDeps],
    serve: list[str],
    port: int | None,
    path: str | None,
    title: str | None,
) -> str:
    """Run a server as the View's live, interactive head."""
    sessions = ctx.deps.sandbox_sessions
    if sessions is None:
        return "The live view is unavailable — your computer isn't available right now."
    if port is None:
        raise ModelRetry("`serve` needs the `port` the server listens on.")
    try:
        handle = await sessions.start_preview(ctx.deps.sandbox_key, serve, port)
    except SandboxError as exc:
        return f"The live server did not start: {exc}"
    # Point the operator's iframe at the entry path so a static server whose root
    # would list the directory (`python -m http.server` with no `index.html`)
    # renders the page instead.
    url = handle.url_for(path)
    ctx.deps.run.emit(
        ViewLive(
            conversation_id=ctx.deps.sandbox_key,
            url=url,
            title=title,
            command=" ".join(handle.command),
            port=port,
        )
    )
    return f"Live view running at {url} (serving '{' '.join(handle.command)}')."


def view_toolset() -> FunctionToolset[RunDeps]:
    toolset: FunctionToolset[RunDeps] = FunctionToolset()

    @toolset.tool
    async def show(
        ctx: RunContext[RunDeps],
        title: str | None = None,
        file: str | None = None,
        serve: list[str] | None = None,
        port: int | None = None,
        path: str | None = None,
    ) -> str:
        """Show the operator what you built, in this conversation's View — a single
        canvas beside the chat with a version history to compare against.

        Pick exactly one of:
        - ``file``: a file you created — an HTML page, an image or chart, a code
          snippet. Captured as a new comparable version of the View.
        - ``serve`` + ``port``: the argv of a live server (e.g. ``["python", "-m",
          "http.server", "8000"]`` or ``["npm", "run", "dev"]``) and the port it
          listens on. Becomes the live, interactive head, replacing any already
          running here. The server must bind ``0.0.0.0`` (not ``127.0.0.1``) and
          serve assets with relative URLs. If the server's root would show a
          directory listing (``python -m http.server`` with no ``index.html``),
          pass ``path`` for the entry file (e.g. ``"index.html"``) — or serve an
          ``index.html``. Returns once the server is up.

        ``title`` labels the View. Use this to *show* a result, not to store data."""
        if (file is None) == (serve is None):
            raise ModelRetry(
                "Pass exactly one of `file` (show a file you made) or `serve` (run a "
                "live server) — not both, not neither."
            )
        if serve is not None:
            return await _show_live(ctx, serve, port, path, title)
        assert file is not None  # narrowed by the exactly-one check above
        return await _show_file(ctx, file, title)

    @toolset.tool
    async def close(ctx: RunContext[RunDeps]) -> str:
        """Stop the live head of this conversation's View, if one is running. The
        saved versions stay; this only tears down the running server."""
        sessions = ctx.deps.sandbox_sessions
        if sessions is None:
            return "The live view is unavailable — your computer isn't available right now."
        await sessions.stop_preview(ctx.deps.sandbox_key)
        ctx.deps.run.emit(ViewLiveStopped(conversation_id=ctx.deps.sandbox_key))
        return "Stopped the live view."

    return toolset
