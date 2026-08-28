"""Toolsets whose tools are fixed but whose *root* is not.

Three categories wrap a `pydantic_ai_harness` toolset that is constructed around a
directory — `files`, `shell`, `repo`. Categories are assembled once at app startup and
shared by every conversation, so none of them can bake its root in at construction.

`AbstractToolset.for_run(ctx)` is not the hook for this, and it is worth saying why since
it looks like it: the library does call it once per run, but a harness toolset's `for_run`
rebuilds from **construction-time** values (`ShellToolset.for_run` passes its own
`_initial_cwd`). It isolates mutable per-run state — a `cd` that drifted the cwd, a
background process handle — between concurrent runs, which is real and useful, but it
cannot root two conversations at two different directories. That is exactly what is
needed here.

So the shape is: answer `get_tools` from a template bound to no real directory, because a
tool's *definition* — name, description, JSON schema — does not depend on where it will
act, which is what keeps the operator-facing catalog identical to the agent's real stack;
then re-resolve the tool from a correctly-rooted instance inside `call_tool`. Pydantic AI
dispatches through `tool.call_func`, which is bound to the instance that produced it, so
delegating the call alone would still act on the template's root. That is the whole trick.

> A test that would pass while being wrong: "two runs don't share a cwd" is satisfied by
> `for_run` alone, with both runs rooted at the template's path. Assert the **roots
> differ and match their own conversations' workspaces**.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic_ai import AbstractToolset, RunContext, ToolsetTool

from services.projects.worktree import WorktreeBusyError
from services.workspace import RunWorkspace

from .deps import RunDeps
from .workspace import run_workspace, unavailable

# Bound toolsets are cached per root because building one registers every tool and
# generates its schema — too much to repeat on each call. They hold no state beyond the
# resolved root, so conversations sharing one are independent. The cap keeps a long-lived
# process from retaining an entry per conversation ever opened.
_MAX_BOUND = 64

#: A `call_tool` guard: raise (or return a string, by raising nothing and letting the
#: caller proceed) before the bound toolset acts. Used for the approval gate on `shell`.
type Guard = Callable[[str, RunContext[RunDeps], RunWorkspace], str | None]


class WorkspaceToolset(AbstractToolset[RunDeps]):
    """A harness toolset, rebound to each run's workspace."""

    def __init__(
        self,
        name: str,
        template: AbstractToolset[RunDeps],
        build: Callable[[Path], AbstractToolset[RunDeps]],
        *,
        guard: Guard | None = None,
    ) -> None:
        self._id = name
        self._template = template
        self._build = build
        self._guard = guard
        self._bound: OrderedDict[str, AbstractToolset[RunDeps]] = OrderedDict()
        # Resolved tools per bound toolset, keyed by object identity and evicted with it.
        self._tools: dict[int, dict[str, ToolsetTool[RunDeps]]] = {}

    @property
    def id(self) -> str:
        return self._id

    @property
    def tools(self) -> dict[str, Any]:
        """The static registry ``tools/catalog.py`` enumerates for the settings surface.
        Read from the template, so the catalog is the same set every run is offered."""
        return getattr(self._template, "tools", {})

    async def get_tools(self, ctx: RunContext[RunDeps]) -> dict[str, ToolsetTool[RunDeps]]:
        return await self._template.get_tools(ctx)

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext[RunDeps],
        tool: ToolsetTool[RunDeps],
    ) -> Any:
        try:
            workspace = await run_workspace(ctx)
        except WorktreeBusyError as exc:
            return str(exc)
        if workspace is None:
            return unavailable(ctx.deps)
        if self._guard is not None:
            refusal = self._guard(name, ctx, workspace)
            if refusal is not None:
                return refusal
        bound = self._for(workspace.root)
        # Re-resolve the tool against the bound toolset: the object handed in carries the
        # template's function, which would act on the template's root. Resolved from the
        # per-root cache rather than by rebuilding the whole dict — the set is fixed for a
        # given root, and this runs on every single call.
        tools = await self._tools_for(bound, ctx)
        return await bound.call_tool(name, tool_args, ctx, tools[name])

    async def _tools_for(
        self, bound: AbstractToolset[RunDeps], ctx: RunContext[RunDeps]
    ) -> dict[str, ToolsetTool[RunDeps]]:
        """The bound toolset's resolved tools, built once per root.

        Keyed by the toolset object's identity so it is evicted with it — a stale entry
        for a reaped workspace would otherwise hand back tools bound to a directory that
        no longer exists.
        """
        cached = self._tools.get(id(bound))
        if cached is None:
            cached = await bound.get_tools(ctx)
            self._tools[id(bound)] = cached
        return cached

    def _for(self, root: Path) -> AbstractToolset[RunDeps]:
        key = str(root)
        bound = self._bound.pop(key, None)
        if bound is None:
            bound = self._build(root)
            if len(self._bound) >= _MAX_BOUND:
                _, evicted = self._bound.popitem(last=False)
                self._tools.pop(id(evicted), None)
        self._bound[key] = bound
        return bound
