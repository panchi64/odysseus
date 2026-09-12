"""The research feature — now a *mode*, and the history of the two things it used to be.

Research has been reduced twice, and what is left here is the residue of both.

It was a pipeline: a rounds loop with its own store, its own REST surface, its own progress
protocol, and a report that arrived finished. That went when research became a conversation
in research mode — what a research thread *is*, it inherits from the chat backbone
(`routes/chat.py`'s composition), and what makes it *research* is three rows in the mode
registry (`services/modes.py`): a prompt, a higher round-trip floor, and the sandbox
workspace every non-code thread gets.

Then it was also a thread-*opener* — an abstract launcher, an implementation that composed
a linked turn, and two tools (`research_start` / `research_read`) the agent polled. That
went too, because the sub-agent engine is the same machine generalized and does it better:
a `researcher` in `services/subagents/roster.py` is composed the same way, reports back
without being polled, and shows the operator a card while it works. So this manifest no
longer contributes a toolset, a capability or a dormant category, and it no longer has to
build after every feature that contributes to a turn — it composes none.

What is left is two things that outlive their machinery.

The **carryover** (`services/research_carryover.py`) is the one-shot that turns the
operator's pre-refactor research rows into threads. It belongs to this feature because
those rows are this feature's history, and it runs here rather than in the migration that
retired the table because a message is sealed with the vault and schema upgrades run before
unlock.

The **scope** survives its surface. `/research` is gone — a research thread is reached
through `/chat` and `/conversations` like every other thread — so this claims no prefix and
grants no reach. It is declared anyway: a token the operator already issued carries the id,
and a scope the table has never heard of is one that fails validation. A name kept costs
nothing; a name withdrawn breaks a live token.
"""

from __future__ import annotations

from core.api_scopes import ScopeClaim
from harness.manifest import FeatureManifest, FeatureRuntime, HarnessContext
from services.research_carryover import seed_carried_research


async def _build(ctx: HarnessContext) -> FeatureRuntime:
    # Fired here rather than in the migration that retired the table because a message is
    # sealed with the vault and schema upgrades run before unlock; it waits for the key
    # itself, does nothing on an installation with no such rows, and drops its own holding
    # table once it has drained it.
    ctx.lifecycle.track("research-carryover", seed_carried_research(ctx.engine, ctx.vault))
    return FeatureRuntime()


MANIFEST = FeatureManifest(
    name="research",
    api_scopes=(ScopeClaim("research", ()),),
    build=_build,
)
