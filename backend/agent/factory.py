"""Constructing the Pydantic AI ``Agent`` a turn runs on.

One function, called once per turn (and stashed whole on a ``ParkedTurn``, so every
approval resume inherits exactly the agent its park was built with). It is the single
place that decides what the model is *told* and what it is *offered*: the two prompt
seams split by durability, the capabilities that observe or rewrite a request on its way
out, the feature-contributed instruction providers, the standing index of the groups this
installation withholds, and the three parts that are the thread's own — its mode, its
permission level and today's date.

It lives apart from ``engine.py`` because it changes for a different reason: a new
capability, a new prompt seam or a new thread-scoped instruction touches this file and
nothing about the run lifecycle. It knows nothing about runs, streams or settings —
everything it needs arrives as an argument.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from types import MappingProxyType
from typing import Any

from pydantic_ai import (
    Agent,
    DeferredToolRequests,
    RunContext,
)
from pydantic_ai.capabilities import ReinjectSystemPrompt
from pydantic_ai.models import Model

from core.timezone import local_zone_key
from prompts.agent import (
    CURRENT_DATE,
    INSTRUCTIONS,
    SYSTEM_PROMPT,
)
from services.llm import TOOL_CALL_SETTINGS
from services.modes import mode_spec
from services.permissions import permission_spec
from tools import (
    InstructionProvider,
    RunDeps,
    build_agent_toolsets,
    dormant_index_instructions,
    tool_search_capability,
)
from tools.describe import category_names

from .injections import AnnounceInjections, contributor_id
from .overhead import MeasureOverhead

# The default for a turn composed without the app's dormant declarations — a stateless
# eval or a test that passes no catalog either. Read-only, so a shared default cannot
# become one turn's leftovers on the next.
NO_DORMANT: Mapping[str, str] = MappingProxyType({})


def build_agent(
    model: Model,
    *,
    categories: Any = None,
    instruction_providers: Sequence[InstructionProvider] = (),
    dormant: Mapping[str, str] = NO_DORMANT,
) -> Agent:
    # Two prompt seams by durability: SYSTEM_PROMPT (identity/voice) is anchored in
    # history; INSTRUCTIONS (autonomy, tool posture, the treat-external-content-as-
    # data guardrail) are rebuilt fresh from the agent every turn, so a poisoned or
    # reconstructed history can never displace them. ReinjectSystemPrompt keeps the
    # system prompt — the half that *does* live in history — authoritative too,
    # stripping any spoofed system part and reasserting ours on every request.
    # output_type accepts DeferredToolRequests so approval-required tools can defer
    # instead of executing; normal turns still return text.
    #
    # ``dormant`` is category → one-line summary for the groups this installation withholds
    # until the model asks for them (`tools/tool_search.py`). The names are what the toolset
    # stack defers; the summaries are what the index below advertises. Both halves are read
    # from the one mapping, so a group can never be held back without being announced.
    # The membership map they resolve against is the assembled catalog's own; a turn that
    # passes no catalog passes no dormant declarations either, so an empty map is exact
    # rather than a guess.
    names_by_category = category_names(categories) if categories is not None else {}
    agent = Agent(
        model,
        deps_type=RunDeps,
        system_prompt=SYSTEM_PROMPT,
        instructions=INSTRUCTIONS,
        toolsets=build_agent_toolsets(categories, dormant=tuple(dormant)),
        # Parallel tool calling (see `services.llm.TOOL_CALL_SETTINGS`). Declared at
        # construction, not per-run on `agent.iter(...)`: a park stashes this agent on
        # the ParkedTurn, so every resume inherits it with nothing threaded through the
        # payload. The library merges run-level settings over these, so it's a default
        # a future per-run knob can still override.
        model_settings=TOOL_CALL_SETTINGS,
        output_type=[str, DeferredToolRequests],
        # ReinjectSystemPrompt keeps our system prompt authoritative — it transforms only
        # what the model sees, never what we persist. Nothing else rewrites the history on
        # its way to the model: a tool result rides into context whole, and the one
        # reduction that exists (conversation compaction) fires in the orchestrator
        # prelude against projected context pressure — or, when a provider refuses an
        # over-long request anyway, once between that request and its retry. Never
        # underneath reasoning already in flight.
        # `MeasureOverhead` and `AnnounceInjections` are listed *after*
        # `ReinjectSystemPrompt` so they read the request as it actually ships rather than
        # before the system prompt is reasserted. Both observe and return the request
        # context untouched, and they are two capabilities rather than one pass over the
        # same parts because they answer different questions and change for different
        # reasons: one sizes the brief for the gauge, the other reports what it said.
        # `tool_search_capability` is ours rather than the library's auto-injected
        # `ToolSearch`: the stock strategy ranks *tools* by word overlap, where a turn that
        # decides it needs the browser needs the whole browser, and its ten-result cap would
        # hand back half a group. Passing one at all is what replaces the default — the
        # library orders it outermost wherever it sits in this list, so the two observers
        # above still read the request as it ships, with the deferred schemas already gone.
        capabilities=[
            ReinjectSystemPrompt(replace_existing=True),
            MeasureOverhead(),
            AnnounceInjections(),
            tool_search_capability(names_by_category, dormant),
        ],
    )

    # Feature-contributed dynamic instructions (each manifest's `instructions` export —
    # the skill catalog): re-resolved fresh each turn, so they're always current and,
    # unlike an appended prompt, never accumulate in history. Each resolves its own
    # capability from the run's bag and no-ops (returns "") when the capability isn't
    # wired, so registration is unconditional. Instructions render at the *head* of
    # every request — keep them small and low-churn, or they invalidate the inference
    # engine's prompt-prefix cache for the whole history behind them (volatile context
    # belongs in a manifest's `prompt_context` export instead, delivered at the tail).
    #
    # `name=` is what makes the context readout's per-provider rows possible: the library
    # stamps the resolved part with that name, so `agent/overhead.py` reads each block off
    # the assembled request instead of measuring providers as they run — and
    # `agent/injections.py` reads the same name to announce what the block said.
    for provider in instruction_providers:
        agent.instructions(name=contributor_id(provider))(provider)

    # The standing index of the withheld groups — a name and a line each, no schemas.
    # Registered here rather than arriving with the providers above because it is not a
    # feature's contribution: what is dormant is decided by assembly, and the same mapping
    # that decided it is what this reads. Deferral is invisible by construction, so without
    # the index a model would answer that it cannot open a page while the browser sits one
    # `search_tools` call away. Resolves to "" when nothing is dormant (or when the
    # operator has switched a group off entirely), which is why it is unconditional.
    dormant_index = dormant_index_instructions(dormant, names_by_category)
    agent.instructions(name=contributor_id(dormant_index))(dormant_index)

    @agent.instructions(name="mode")
    def _mode_posture(ctx: RunContext[RunDeps]) -> str:
        """The thread's mode, where it has something of its own to say — read off the
        registry, so a mode's prose lives with the rest of that mode's declaration rather
        than in a branch here. Most modes add nothing and resolve to "" (see
        `prompts/modes.py`), which is why this is unconditional."""
        return mode_spec(ctx.deps.mode).instructions

    @agent.instructions(name="level")
    def _level_posture(ctx: RunContext[RunDeps]) -> str:
        """What the thread's permission level means for how the model works — read off the
        registry beside the mode, for the same reason. The level is *enforced* whether or
        not the model is told (Plan by withholding the tools, the rest by parking), so this
        is not a control; it is the explanation for what the model is about to run into.
        Two of the four levels have nothing to add and resolve to "" (see
        `prompts/levels.py`), which is why this is unconditional."""
        return permission_spec(ctx.deps.permission).instructions

    @agent.instructions(name="date")
    def _current_date() -> str:
        """Give the agent today's date as a dynamic instruction — re-resolved fresh each
        turn (always current, no stale pinned copy) and kept out of history.

        The zone travels with it. Everything downstream already runs on the operator's own
        clock — `builtin_now`, a calendar tool's default timezone — and the model was the
        one participant never told which clock that is, so "tomorrow at nine" was being
        resolved against an assumption rather than a fact."""
        now = datetime.now().astimezone()
        # Avoid strftime "%-d"/"%#d" platform splits — build the day number directly so
        # this stays portable across POSIX hosts.
        stamp = f"{now:%A, %B} {now.day}, {now.year}"
        return CURRENT_DATE.format(date=stamp, zone=local_zone_key())

    return agent
