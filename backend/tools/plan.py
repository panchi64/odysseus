"""The agent's own task list — the plan the operator watches it work through.

``pydantic_ai_harness.Planning`` owns the tools and their model-facing wording; we supply
the storage (``services/plans`` — sealed, per-conversation) and the surface.

**Registered as a toolset, not as a capability, on purpose.** The capability form also
injects the plan as a tail reminder through its own model-request hook. Taking it whole
would have put six tools outside the one thing every other tool passes through: the
namespaced, operator-toggleable catalog (``tools/catalog.py``) whose promise is that the
settings list and the agent's actual stack cannot diverge. So the toolset comes from the
capability and the reminder is re-delivered through the seam this codebase already has for
exactly this — a ``PromptContextProvider``, which lands at the *tail* of the turn's prompt
for the same prompt-cache reason the harness places it there.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any

from pydantic_ai import AbstractToolset, RunContext, ToolsetTool
from pydantic_ai_harness.planning import (
    InMemoryPlanStore,
    Planning,
    PlanStore,
    render_plan,
)

from core.container import ServiceContainer
from services.plans import ConversationPlans, ConversationPlanStore

from .deps import RunDeps

# Rendered above the plan at the tail of the turn. Short and fixed: the block's *content*
# changes constantly, so anything static about it belongs here rather than in the churn.
_PREAMBLE = (
    "Your current task list for this conversation. Keep it accurate as you work — "
    "mark a task in_progress when you start it and completed when it is done."
)


# One bound toolset per conversation, kept because building one registers six tools and
# generates their schemas. Bounded so a long-lived process doesn't retain an entry for
# every thread ever opened.
_MAX_BOUND = 64


def _store_for(ctx: RunContext[RunDeps]) -> PlanStore:
    """The store this run's plan lives in — sealed and per-conversation where there is
    one, in memory for the life of the run where there isn't."""
    plans = ctx.deps.caps.get_optional(ConversationPlans)
    conversation_id = ctx.deps.conversation_id
    if plans is None or conversation_id is None:
        # No conversation to key on (a one-off run), or no store wired: plan in memory.
        # Planning still works; it simply doesn't outlive the run.
        return InMemoryPlanStore()
    return ConversationPlanStore(
        plans,
        owner_id=ctx.deps.run.owner_id,
        conversation_id=conversation_id,
        run=ctx.deps.run,
    )


class _ConversationPlanToolset(AbstractToolset[RunDeps]):
    """The ``plan`` category, rebound to whichever conversation is asking.

    **The rebinding is the whole point.** ``Planning.resolve_store`` memoises its store on
    the capability instance the first time it is asked, and a category object is built once
    for the whole app — so a single shared capability would hand *every* conversation the
    first one's plan: thread B would read and overwrite thread A's tasks. Registering the
    capability's toolset directly is only safe under ``for_run()``, the per-run clone hook
    that a toolset registration never reaches. So each conversation gets its own capability
    (hence its own memoised store), resolved here.

    Shaped like ``tools/files.py``: ``get_tools`` answers from a template, because a tool's
    definition doesn't depend on whose plan it will touch — which keeps the offered set,
    the operator catalog and the enabled gate identical for every thread.
    """

    def __init__(self, template: AbstractToolset[RunDeps]) -> None:
        self._template = template
        self._bound: OrderedDict[str, tuple[AbstractToolset[RunDeps], PlanStore]] = (
            OrderedDict()
        )

    @property
    def id(self) -> str:
        return "plan"

    @property
    def tools(self) -> dict[str, Any]:
        """The static registry ``tools/catalog.py`` enumerates for the settings surface."""
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
        bound, store = self._for(ctx)
        # The store is cached with the toolset, but the run it emits on is per turn — point
        # it at the live one, or the second turn's updates stream onto a dead run.
        if isinstance(store, ConversationPlanStore):
            store.bind_run(ctx.deps.run)
        # Re-resolve against the bound toolset: the tool handed in carries the template's
        # function, which is wired to the template's (unbound) store.
        return await bound.call_tool(name, tool_args, ctx, (await bound.get_tools(ctx))[name])

    def _for(self, ctx: RunContext[RunDeps]) -> tuple[AbstractToolset[RunDeps], PlanStore]:
        # Keyed by conversation where there is one, else by run: a conversation's plan
        # outlives its turns, a one-off run's does not.
        key = ctx.deps.conversation_id or f"run:{ctx.deps.run.id}"
        entry = self._bound.pop(key, None)
        if entry is None:
            store = _store_for(ctx)
            capability = Planning[RunDeps](store_resolver=lambda _ctx: store)
            entry = (capability.get_toolset(), store)
            if len(self._bound) >= _MAX_BOUND:
                self._bound.popitem(last=False)
        self._bound[key] = entry
        return entry


def plan_toolset() -> AbstractToolset[RunDeps]:
    """The ``plan`` category — the model's read/write access to its own task list."""
    # The template's store is never read or written: only `call_tool` acts, and it always
    # rebinds first. It exists to carry the tool definitions.
    return _ConversationPlanToolset(
        Planning[RunDeps](store_resolver=lambda _ctx: InMemoryPlanStore()).get_toolset()
    )


async def plan_context(
    caps: ServiceContainer, owner_id: str, conversation_id: str | None
) -> str:
    """The current task list, for the tail of this turn's prompt.

    Delivered per turn rather than written into history: the list changes on nearly every
    step, and a changing block at the head of the request would invalidate the inference
    engine's prompt-prefix cache for the whole conversation behind it.
    """
    plans = caps.get_optional(ConversationPlans)
    if plans is None or conversation_id is None:
        return ""
    items = await plans.items(owner_id, conversation_id)
    # No plan, no block. This is also what keeps an operator who disabled the `plan`
    # category from being told to "keep it accurate" with no tools registered to do so:
    # with the tools gone nothing can create a task, so there is nothing to render. A
    # plan left over from before they disabled it still shows — it describes outstanding
    # work, and hiding it would be the more surprising of the two.
    if not items:
        return ""
    return f"{_PREAMBLE}\n\n{render_plan(items)}"
