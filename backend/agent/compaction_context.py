"""Everything a fold needs, settled once per turn.

Compaction can now fire from three places inside one turn — the prelude's projected
trigger, the in-turn recovery after a provider refuses an over-long request, and the same
recovery on a resumed (previously parked) turn. Each needs the identical seven facts, and
none of them is derivable where the second and third fire: ``drive_turn`` has no settings
store, no policy and no utility model, and a parked turn resumes minutes later in a
different orchestrator entirely.

So the facts travel as one frozen value, built where they are known and carried to where
they are used — including onto :class:`~agent.parking.ParkedTurn`, so an approval resume
can recover from an overflow exactly as the original turn would have. A ``None`` context
means "this turn cannot fold" (a stateless run, or compaction switched off), which is a
state the recovery path has to handle anyway.

It lives in its own module rather than in the engine because ``parking.py`` holds one and
the engine imports ``parking``; the other direction would be a cycle.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings

from core.config import Settings
from services.conversations import ConversationStore

from .summarize import AutoCompactPolicy


@dataclass(frozen=True)
class CompactionContext:
    """The resources and policy one turn's folds run under."""

    store: ConversationStore
    conversation_id: str
    policy: AutoCompactPolicy
    # The utility model that writes the summary, with its reasoning-off settings — the
    # same cheap model the namer and the judge use.
    model: Model
    reasoning_off: ModelSettings | None
    settings: Settings
    # The transcript budget for that model: the operator's cap, held under half the
    # summarizer's own window when the endpoint declares one, so the input can never
    # overrun the model that has to read it.
    max_input_tokens: int | None = None


def build_compaction_context(
    *,
    store: ConversationStore | None,
    conversation_id: str | None,
    policy: AutoCompactPolicy,
    model: Model | None,
    reasoning_off: ModelSettings | None,
    settings: Settings,
    utility_context_window: int | None,
) -> CompactionContext | None:
    """The context a fold runs under, or ``None`` when this thread cannot fold at all — no
    conversation to fold (a stateless run) or no utility model to write the summary with.

    **Every trigger builds its context here**, which is the point: the fields are not
    independent, and a caller assembling them by hand picks the ones it happens to know
    about. That is not hypothetical — the operator's own "compact now" used to construct
    its own arguments and omitted ``settings`` and ``max_input_tokens`` entirely, so a
    hand-started fold ran against the raw configured cap while an automatic one ran against
    :func:`resolve_max_input_tokens`'s clamp. On an endpoint declaring a small window that
    is not a cosmetic difference: the manual fold handed the summarizer twice the
    transcript and could fail where the automatic one succeeded.

    So the clamp is applied *in here* rather than at each call site, and the window it
    needs is an argument rather than something a caller may forget to pass."""
    if store is None or conversation_id is None or model is None:
        return None
    return CompactionContext(
        store=store,
        conversation_id=conversation_id,
        policy=policy,
        model=model,
        reasoning_off=reasoning_off,
        settings=settings,
        max_input_tokens=resolve_max_input_tokens(settings, utility_context_window),
    )


def resolve_max_input_tokens(settings: Settings, utility_window: int | None) -> int:
    """The summarizer's input budget: the configured cap, or half the utility model's
    window when that is smaller.

    Half, not all: the summarizer's own instructions and its output share that window with
    the transcript, and a budget that filled it would make the fold fail exactly when the
    thread most needs it. Unknown window ⇒ the configured cap alone, since guessing a
    ceiling for an endpoint that declares none is how a fold silently stops happening."""
    cap = settings.auto_compact_input_max_tokens
    if utility_window is None or utility_window <= 0:
        return cap
    return min(cap, utility_window // 2)
