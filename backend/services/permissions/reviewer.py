"""The model stage — one structured call that scores an action on three named axes.

What reaches here is what the deterministic stage would not vouch for (``judge.py``):
an act whose worst case is real, or one whose worst case could not be read at all. The
question is no longer "is this provably harmless" — it is "did the operator ask for this,
and is it worth what it could cost", which is a judgement about a conversation and
therefore a model's to make.

**Three axes, not one score.** A single "is this ok" number collapses two independent
facts — how bad the act is, and whether it was wanted — and a model asked for the
collapsed answer will trade one against the other silently. Scored apart, the trade is
made *here*, in code someone can read: ``risk`` is a property of the act alone,
``authorization`` a property of the conversation alone, and ``correctness`` is the
free-text observation that catches the case neither number does — the right kind of act
aimed at the wrong thing.

**Two rules copied from LM Studio's design, both load-bearing:**

- **The prompt carries the rubric and never the passing score.** A reviewer told what
  clears the bar optimises for clearing it; a reviewer told only what the words mean
  answers the question it was asked. The combination lives in ``decide.py``, and nothing
  about it is stated here or in the prompt.
- **The transcript excludes tool results.** Everything the model has read from a file, a
  page or an MCP server is content someone else wrote, and a reviewer that saw it could be
  talked into an approval by text the attacker chose — an approval, note, of the very call
  that untrusted text asked for. So the reviewer sees the operator's own messages and the
  assistant's own prose, and nothing that came back from a tool. It is the same posture
  every other ingress in this codebase takes, applied to the one call whose output is a
  permission.

Even so, the transcript that *is* shown goes inside an untrusted fence: the assistant's
prose is downstream of everything it has read, so it can carry an injected argument
forward in its own words. Fencing it means such an argument arrives as something the
reviewer reads about, not as something it is told.

**Degradation is fail-closed and lives at the caller.** This module returns ``None`` for
every failure it can have — no model bound, a timeout, an unparseable answer — and never
a lenient verdict standing in for one. What ``None`` *means* is ``decide.py``'s to say,
and it says park.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings

from core.untrusted import wrap_untrusted
from prompts.utility import REVIEW_INSTRUCTIONS
from services.permissions.capability import Capability

logger = logging.getLogger(__name__)

#: How much of the thread the reviewer reads, in messages, counted from the end. The
#: operator's intent for the call in flight is in the recent turns; the whole thread would
#: cost tokens and latency to re-establish something the last few exchanges already say.
TRANSCRIPT_MESSAGES = 12

#: Per-message cap, so one pasted file in a user message cannot crowd out the ten turns
#: around it. Generous enough that an ordinary request survives whole.
MESSAGE_CHARS = 2_000


class ReviewVerdict(BaseModel):
    """One reviewer's scores. Typed rather than prose for the reason every structured
    utility call in this codebase is: a successful injection can move a label, and can
    never issue an instruction."""

    #: What the act could cost. ``too_destructive`` is unrecoverable, and it is the one
    #: value that overrules everything else — see ``decide.py``.
    risk: Literal["low", "high", "too_destructive"] = "high"
    #: Whether the operator asked for it. Only the operator's own messages count.
    authorization: Literal["explicitly_no", "neutral", "explicitly_yes"] = "neutral"
    #: What about the act does not match the request, in a sentence. None ⇒ it matches.
    correctness: str | None = Field(default=None, max_length=400)


@dataclass(frozen=True)
class ReviewRequest:
    """What a reviewer is given: an action's worst case, and the thread that led to it."""

    capability: Capability
    #: The recent conversation, already filtered to user and assistant prose
    #: (:func:`review_transcript`). Empty is legitimate — a stateless turn has no thread.
    transcript: str


#: The stage as a function, so the engine holds a reviewer rather than a model and a test
#: can substitute one without a model at all. Returns None on any failure (see the module
#: docstring); the caller turns that into a park.
type Reviewer = Callable[[ReviewRequest], Awaitable[ReviewVerdict | None]]


def review_transcript(
    messages: Sequence[ModelMessage],
    *,
    limit: int = TRANSCRIPT_MESSAGES,
    chars: int = MESSAGE_CHARS,
) -> str:
    """The thread as the reviewer may see it: the operator's requests and the assistant's
    prose, in order, and nothing else.

    Three kinds of part are dropped and each for its own reason. **Tool returns** are
    content from outside the conversation and are the injection vector this whole design
    is arranged around. **Tool calls** are the model's own requests, and the one being
    judged is already described far more precisely by its capability. **Thinking** is the
    model's private argument for what it is about to do, which is exactly the material a
    reviewer should not be weighing when deciding whether the *operator* asked for it.
    """
    lines: list[str] = []
    for message in list(messages)[-limit:]:
        if isinstance(message, ModelRequest):
            text = "\n".join(
                _prompt_text(part) for part in message.parts if isinstance(part, UserPromptPart)
            ).strip()
            if text:
                lines.append(f"Operator: {text[:chars]}")
        elif isinstance(message, ModelResponse):
            text = "\n".join(
                part.content for part in message.parts if isinstance(part, TextPart)
            ).strip()
            if text:
                lines.append(f"Assistant: {text[:chars]}")
    return "\n\n".join(lines)


def _prompt_text(part: UserPromptPart) -> str:
    """A user part's words. Multimodal content arrives as a list whose non-text items are
    binary — an image, a document — and have no place in a text transcript."""
    if isinstance(part.content, str):
        return part.content
    return "\n".join(item for item in part.content if isinstance(item, str))


def review_prompt(request: ReviewRequest) -> str:
    """The reviewer's one message: the act, then the conversation it came out of.

    The act sits *outside* the fence and the conversation inside it. That split is the
    point: the capability is this process's own description, extracted from a grammar, and
    the transcript is prose the model wrote after reading whatever it has read.
    """
    capability = request.capability
    lines = [f"Action: {capability.summary}", f"Tool: {capability.tool}"]
    if capability.writes:
        lines.append(f"Writes: {', '.join(capability.writes)}")
    if capability.reads:
        lines.append(f"Reads: {', '.join(capability.reads)}")
    if capability.env_writes:
        lines.append(f"Sets in the environment: {', '.join(capability.env_writes)}")
    if capability.escapes:
        lines.append(f"Reaches outside the workspace: {', '.join(capability.escapes)}")
    if capability.network:
        lines.append("Reaches the network.")
    for note in capability.unbounded:
        lines.append(f"Could not be fully read: {note}")
    body = "\n".join(lines)
    if not request.transcript:
        return f"{body}\n\nThere is no conversation to read: the operator has said nothing."
    return f"{body}\n\nThe conversation so far:\n" + wrap_untrusted(
        request.transcript, source="conversation"
    )


def make_utility_reviewer(
    model: Model,
    *,
    model_settings: ModelSettings | None = None,
    timeout_s: float = 30.0,
    max_tokens: int = 1024,
) -> Reviewer:
    """A reviewer over the cheap utility model, bounded by a timeout it cannot exceed.

    The timeout is not an optimisation. A review runs inside a live turn with the
    operator watching, and a reviewer that hangs would hold a run open indefinitely on a
    call nobody has been asked about — worse than the park it was trying to avoid. So a
    slow model produces ``None``, and ``None`` means park.
    """

    async def review(request: ReviewRequest) -> ReviewVerdict | None:
        agent = Agent(model, output_type=ReviewVerdict, instructions=REVIEW_INSTRUCTIONS)
        settings: ModelSettings = {
            "max_tokens": max_tokens,
            "temperature": 0.0,
            **(model_settings or {}),
        }
        try:
            async with asyncio.timeout(timeout_s):
                result = await agent.run(review_prompt(request), model_settings=settings)
        except TimeoutError:
            logger.warning(
                "auto review timed out for %s — parking instead", request.capability.tool
            )
            return None
        except Exception:  # noqa: BLE001 — every failure degrades to a park, never to an allow
            logger.warning(
                "auto review failed for %s — parking instead",
                request.capability.tool,
                exc_info=True,
            )
            return None
        return result.output

    return review
