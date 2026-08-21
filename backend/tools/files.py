"""Filesystem tools over the agent's own sandbox workspace (`AE-2` Filesystem).

The agent's other way to touch files is ``code_execute``, which means editing by heredoc
and reading by ``cat``. That works and is miserable: every edit rewrites a whole file
through a shell, and every read costs a container round-trip. These tools are the direct
route — read a slice, replace an exact span, grep, glob — so the model spends its turn on
the problem rather than on shell quoting.

**We do not hand-roll them.** ``pydantic_ai_harness.FileSystem`` is the Pydantic team's
own capability: eight tools whose containment (``..``, absolute paths, and symlinks that
``realpath`` outside the root are all rejected), binary detection, hash-checked edits and
``ModelRetry`` errors are theirs to maintain. We supply one thing they cannot know — which
directory this run may touch.

**Which directory is per-conversation, and the category object is not.** Categories are
assembled once at app startup (see ``app.py``) and shared by every conversation, while
each conversation has its own workspace at ``<data_dir>/sandbox/work/<key>/``. So the root
cannot be baked in at construction: :class:`_SandboxFileToolset` resolves it per call from
``ctx.deps.sandbox_key`` and dispatches into a ``FileSystemToolset`` bound to *that*
workspace.

**The isolation invariant holds** (`XC-SEC-7`). That directory is the host side of the
container's ``/work`` bind mount — the box's own scratch space, never the operator's
files — so these tools reach exactly what ``code_execute`` reaches and nothing else. They
are not the host filesystem tools; a host write stays sensitive and approval-gated
(`AE-3.1`). Being confined, they need no approval, exactly as sandboxed execution doesn't.
"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Any

from pydantic_ai import AbstractToolset, RunContext, ToolsetTool
from pydantic_ai_harness import FileSystem
from pydantic_ai_harness.filesystem._toolset import FileSystemToolset

from core.config import get_settings
from services.sandbox import SandboxError, SandboxSessionManager

from .deps import RunDeps

# The model is told its machine is unavailable in the same words `code_execute` uses, so
# a missing runtime reads as one fact about one machine rather than two unrelated faults.
_UNAVAILABLE = (
    "Your computer is unavailable right now: no runtime is configured. Files cannot "
    "be read or written, and nothing will run on the operator's host."
)

# Bound toolsets are cached per workspace because building one registers eight tools and
# generates their schemas — too much to repeat on every call. They hold no state beyond
# the resolved root, so conversations sharing one are independent. The cap keeps a
# long-lived process from retaining an entry per conversation ever opened.
_MAX_BOUND = 64


# Deliberately *not* derived from the seal's exclusion list. Marking those paths read-only
# looked like a kindness — the model can't invest edits in files a reap will drop — but the
# list includes `dist` and `build`, which is where a build the agent just ran puts its
# output. It would have been refused `files_edit_file` on its own artifact while the same
# edit through `code_execute`'s shell succeeded: an asymmetry with no rule behind it, which
# reads to the model as a random failure. The harness's own defaults (`.git/*`, `.env`,
# key files, `**/secrets*`) stay in force; they protect things worth protecting.


class _SandboxFileToolset(AbstractToolset[RunDeps]):
    """The ``files`` category: harness file tools, rebound to each run's workspace.

    ``get_tools`` answers from a template bound to no real directory, because a tool's
    *definition* — name, description, JSON schema — does not depend on which workspace it
    will act on. That keeps the offered set identical for every conversation, which is
    what lets the operator-facing catalog stay honest (``tools/catalog.py`` reads the
    static registry) and the enabled gate keep matching on stable names.

    ``call_tool`` is where the workspace matters. Pydantic AI dispatches through
    ``tool.call_func``, which is bound to the instance that produced it, so delegating the
    call is not enough — the tool has to be re-resolved from a toolset rooted at *this*
    run's workspace. That is the whole trick, and the reason this class exists.
    """

    def __init__(self, template: FileSystemToolset[RunDeps]) -> None:
        self._template = template
        self._bound: OrderedDict[str, FileSystemToolset[RunDeps]] = OrderedDict()
        # Resolved tools per bound toolset, keyed by object identity and evicted with it.
        self._tools: dict[int, dict[str, ToolsetTool[RunDeps]]] = {}

    @property
    def id(self) -> str:
        return "files"

    @property
    def tools(self) -> dict[str, Any]:
        """The static registry ``tools/catalog.py`` enumerates for the settings surface."""
        return self._template.tools

    async def get_tools(self, ctx: RunContext[RunDeps]) -> dict[str, ToolsetTool[RunDeps]]:
        return await self._template.get_tools(ctx)

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext[RunDeps],
        tool: ToolsetTool[RunDeps],
    ) -> Any:
        sessions = ctx.deps.caps.get_optional(SandboxSessionManager)
        if sessions is None:
            # These tools only need the workspace *directory*, not a container — but the
            # directory exists to be the box's `/work`, and with no runtime nothing the
            # agent writes there can ever be run, previewed, or reached by `code_execute`.
            # So they ride the sandbox's availability rather than offering a filesystem
            # detached from anything that could use it, and say so in the same words
            # `code_execute` does.
            return _UNAVAILABLE
        try:
            session = await sessions.acquire(ctx.deps.sandbox_key)
            workspace = session.ensure_workspace()
        except SandboxError as exc:
            # A locked vault or an unreadable seal is infrastructure, not the model's
            # mistake — hand it back as something to read rather than raising into the run.
            return f"Your files could not be opened: {exc}"
        bound = self._for(workspace)
        # Re-resolve the tool against the bound toolset: the object handed in carries the
        # template's function, which would act on the template's root. Resolved from the
        # per-workspace cache rather than by rebuilding the whole tool dict — the set is
        # fixed for a given workspace, and this runs on every single file tool call.
        tools = await self._tools_for(bound, ctx)
        return await bound.call_tool(name, tool_args, ctx, tools[name])

    async def _tools_for(
        self, bound: FileSystemToolset[RunDeps], ctx: RunContext[RunDeps]
    ) -> dict[str, ToolsetTool[RunDeps]]:
        """The bound toolset's resolved tools, built once per workspace.

        Keyed by the toolset object's identity so it is evicted with it — a stale entry
        for a reaped workspace would otherwise hand back tools bound to a directory that
        no longer exists.
        """
        cached = self._tools.get(id(bound))
        if cached is None:
            cached = await bound.get_tools(ctx)
            self._tools[id(bound)] = cached
        return cached

    def _for(self, workspace: Path) -> FileSystemToolset[RunDeps]:
        key = str(workspace)
        bound = self._bound.pop(key, None)
        if bound is None:
            bound = _toolset_for(workspace)
            if len(self._bound) >= _MAX_BOUND:
                _, evicted = self._bound.popitem(last=False)
                self._tools.pop(id(evicted), None)
        self._bound[key] = bound
        return bound


def _toolset_for(root: Path) -> FileSystemToolset[RunDeps]:
    settings = get_settings()
    return FileSystem[RunDeps](
        root_dir=root,
        max_read_lines=settings.sandbox_files_max_read_lines,
    ).get_toolset()


def files_toolset() -> AbstractToolset[RunDeps]:
    """The ``files`` category, built once at app assembly and shared by every run."""
    # The template's root is never read from or written to — only `call_tool` acts, and it
    # always rebinds first. It exists to carry the tool definitions.
    return _SandboxFileToolset(_toolset_for(Path("/nonexistent-template-root")))
