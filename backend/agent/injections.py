"""Saying out loud what the chassis put in front of the model.

Every turn carries text the operator never wrote and never sees: the project's own
`CLAUDE.md`, the skill catalog, the plan reminder, today's date, whatever a manifest
contributes. The context gauge has always been able to say what those *cost* — that is
``services.context_budget`` — and has never been able to say what they *said*. Those are
different questions, and only the second one accounts for a model that behaves as though
it had been told something nobody in the thread told it.

So each contribution is announced on the run's own stream as it is assembled, ahead of
the work it shaped. The event is deliberately not a tool call and must not render as one:
a tool call is the model reaching out, and this is the chassis reaching in.

**Two seams, because the engine has two.** An ``InstructionProvider`` resolves inside the
library while a request is assembled, so it is read back off that request through the
``AnnounceInjections`` capability — the same public hook ``agent.overhead`` measures from,
and for the same reason: that is where the brief exists as *parts* with the name each was
contributed under. A ``PromptContextProvider`` resolves in the engine before the agent
starts, so the engine announces it directly. Both land in one event type, distinguished by
``placement``, because the operator's question is "what was I not shown", not "which of
our two registration seams delivered it".

**Announced once per turn, per distinct text.** The instruction hook fires on every model
request, so a five-step turn resolves the same brief five times; repeating it would bury
the turn's real work under a fivefold echo of its preamble. What is *not* deduplicated is
a contributor whose text changed mid-turn — a plan reminder that grew a task genuinely is
a new injection, and seeing it arrive is the point.

**The dedup key is a digest, never the block itself.** The capability lives as long as the
agent does — and a turn parked for approval holds it for as long as the operator takes to
answer — so a key built from the full text would pin one retained copy of every distinct
brief for that whole time, a repo brief being budgeted at 64KB. A digest answers the only
question the key is asked (has this exact text already been announced) at a fixed
thirty-odd bytes.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic_ai import InstructionPart, RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.models import ModelRequestContext

from core.text import truncate_on_boundary
from runs import INJECTED_TEXT_LIMIT, ContextInjected, Run
from services.context_budget import CHARS_PER_TOKEN_PROSE
from tools.deps import RunDeps


def contributor_id(provider: Callable[..., Any]) -> str:
    """The slug a provider's contribution is filed under — its own name, minus the
    suffix the convention gives it (``skill_catalog_instructions`` → ``skill_catalog``,
    ``plan_context`` → ``plan``).

    Handed to ``agent.instructions(name=…)``, so it becomes the name the library stamps
    on the part this provider resolves to, the row ``agent/overhead.py`` reports, and the
    ``contributor`` on the event below. One derivation, so the gauge's breakdown and the
    work log's injection row can never name the same block differently.

    Derived rather than declared because a provider is a plain callable and giving every
    manifest a label field would be ceremony for a readout row. A rename therefore renames
    the row, which is the honest failure: the client de-slugs whatever it is given, so the
    worst case is a row reading "Skill catalog" instead of "Skills" — never a wrong number.
    """
    name = getattr(provider, "__name__", "") or "instructions"
    stripped = name.strip("_").removeprefix("instructions_")
    for suffix in ("_instructions", "_context"):
        stripped = stripped.removesuffix(suffix)
    return stripped or "base"


def injected_tokens(text: str) -> int:
    """A contribution's size, on the prose rate the composition readout already uses.

    Not ``conversation_view.estimate_tokens``' flat four-characters-a-token: these blocks
    are prose and land in the standing brief, so counting them at the brief's own rate is
    what keeps an injection row and the gauge segment it belongs to from disagreeing about
    the same text. Coarse either way — every surface renders it with a `~`."""
    return round(len(text) / CHARS_PER_TOKEN_PROSE)


def announce_injection(
    run: Run, contributor: str, text: str, placement: Literal["instructions", "prompt"]
) -> None:
    """Emit one contribution onto the run's stream.

    ``tokens`` is measured over the whole block, before the wire cap is applied, so a
    truncated preview never understates what the turn actually paid for it."""
    body = truncate_on_boundary(text, INJECTED_TEXT_LIMIT)
    run.emit(
        ContextInjected(
            contributor=contributor,
            placement=placement,
            tokens=injected_tokens(text),
            text=body,
            truncated=len(body) < len(text),
        )
    )


@dataclass
class AnnounceInjections(AbstractCapability[RunDeps]):
    """Announce the standing brief's named contributors as each request goes out.

    A capability rather than a wrapper around every provider for the reason
    :class:`agent.overhead.MeasureOverhead` is one: the hook is the only place the brief
    exists as parts carrying the name each was contributed under. A shim per provider
    would have to be installed by whoever registers them and would miss the two the engine
    registers itself.

    **Unnamed parts are not announced.** Those are our own literal instructions and the
    separators the library joins parts with — the fixed brief, identical on every turn of
    every thread, which the gauge already reports as ``base``. A row for it in every work
    log would be the one injection the operator can neither act on nor switch off.

    Observes only: the request context is returned exactly as it arrived.
    """

    #: Contributor and a digest of the text already announced on this turn — see the
    #: module docstring on why the text is part of the key, and why only its digest is.
    seen: set[tuple[str, str]] = field(default_factory=set)

    async def before_model_request(
        self, ctx: RunContext[RunDeps], request_context: ModelRequestContext
    ) -> ModelRequestContext:
        # Defensive on the deps hop alone, exactly as the overhead capability is: an agent
        # built without our deps (a bare test harness) costs the readout, never the turn.
        run = getattr(ctx.deps, "run", None)
        if run is not None:
            self.announce(run, request_context.model_request_parameters.instruction_parts)
        return request_context

    def announce(self, run: Run, parts: list[InstructionPart] | None) -> None:
        for part in parts or ():
            name = part.id.name if part.id is not None else None
            if not name or not part.content:
                continue
            key = (name, _digest(part.content))
            if key in self.seen:
                continue
            self.seen.add(key)
            announce_injection(run, name, part.content, "instructions")


def _digest(text: str) -> str:
    """A short content fingerprint for the dedup key. BLAKE2b truncated to 128 bits:
    this decides whether the operator sees a duplicate row, not whether anything is
    trusted, and a collision at that width will not happen before the heat death."""
    return hashlib.blake2b(text.encode("utf-8"), digest_size=16).hexdigest()
