"""The research feature — a *mode*, and the agent's way of opening a thread in it.

Research was a pipeline: a rounds loop with its own store, its own REST surface, its own
progress protocol, and a report that arrived finished. It is now a conversation in
research mode, which means almost all of that machinery is gone rather than rewritten —
what a research thread *is*, it inherits from the chat backbone (`routes/chat.py`'s
composition), and what makes it *research* is three rows in the mode registry: a prompt
that says gather before you conclude, a higher round-trip ceiling, and the sandbox
workspace every non-code thread gets.

So this manifest contributes two things. The first is the implementation behind
`services/research_threads.py` (built in `_research_threads.py` beside this file), so
`tools/research.py` can open such a thread from inside another one without importing turn
composition, which sits above `tools/`. It is built here for the same reason the
scheduler's task executor is built in its own manifest — a tool has no `Request`, so a
launcher that closed over one could never be reached from inside a run, and here every
handle it needs is already resolved.

The second is the one-shot that carries the operator's *old* research rows into threads
(`services/research_carryover.py`). It belongs to this feature because those rows are this
feature's history, and it runs here rather than in the migration that retired the table
because a message is sealed with the vault and schema upgrades run before unlock.

**A linked thread notifies like any other thread**, because it *is* one: the
conversation-linked run-terminal policy in the notifications manifest already announces a
run that finishes against a conversation, so the research-shaped hook this manifest used
to carry is gone rather than generalised.
"""

from __future__ import annotations

from core.api_scopes import ScopeClaim
from harness.manifest import FeatureManifest, FeatureRuntime, HarnessContext
from harness.manifests._research_threads import ConversationResearchThreads
from services.research_carryover import seed_carried_research
from services.research_threads import ResearchThreads
from tools.research import research_toolset


async def _build(ctx: HarnessContext) -> FeatureRuntime:
    threads = ConversationResearchThreads(ctx)
    # The operator's pre-refactor research rows, turned into the threads they should
    # always have been. Fired here rather than in the migration that retired the table
    # because a message is sealed with the vault and schema upgrades run before unlock;
    # it waits for the key itself, does nothing on an installation with no such rows, and
    # drops its own holding table once it has drained it.
    ctx.lifecycle.track(
        "research-carryover", seed_carried_research(ctx.engine, ctx.vault)
    )
    return FeatureRuntime(
        services=(threads,),
        # Registered under the abstract type so `tools/research.py` can resolve it
        # without importing this wiring layer, which sits above `tools/`.
        capabilities=((threads, ResearchThreads),),
    )


MANIFEST = FeatureManifest(
    name="research",
    # Opening a thread composes a full interactive turn, so every feature contributing to
    # that turn's capability set must have built first — the same list the scheduler's
    # task executor works under, and for the same reason.
    after=(
        "calendar",
        "corpus",
        "external",
        "mail",
        "memory",
        "notifications",
        "secret-vault",
        "skills",
        "uploads",
        "views",
        "web",
    ),
    # The scope survives its surface. `/research` is gone — a research thread is reached
    # through `/chat` and `/conversations` like every other thread — so this claims no
    # prefix and grants no reach of its own. It is declared anyway: a token the operator
    # already issued carries the id, and a scope the table has never heard of is one that
    # fails validation. A name kept costs nothing; a name withdrawn breaks a live token.
    api_scopes=(ScopeClaim("research", ()),),
    toolsets=(("research", research_toolset),),
    build=_build,
)
