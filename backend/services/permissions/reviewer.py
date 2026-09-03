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

  **Including the tool results a compaction folded.** A conversation compaction writes its
  summary back as a *user* message (``services/conversations.py``), and that summary is
  built from the whole thread, tool returns and all (``agent/summarize.py``) — so a page
  the agent read once reaches this file wearing the one label the rubric treats as
  authorising. It is dropped by the marker it is written with. The cost is real and is the
  right way round: after a compaction the reviewer reads only the turns since, which is
  less to authorize on, and less authorization parks.

Even so, the transcript that *is* shown goes inside an untrusted fence: the assistant's
prose is downstream of everything it has read, so it can carry an injected argument
forward in its own words. Fencing it means such an argument arrives as something the
reviewer reads about, not as something it is told.

**Two things follow from that, and both are about who wrote which byte.** The prompt is
split down that line rather than by topic: what *this process* derived — the tool's name,
the paths the walk found, whether the command reaches the network, what could not be read
— stands in the clear, and every byte the *model* authored — the action's summary, and so
the command inside it — sits inside the fence with the conversation. And the conversation
is handed over as **JSON entries, not labelled lines**: a transcript rendered as
`Operator: …` is a format any message can write, so an assistant turn (or a pasted page
quoted in one) could open a second "Operator:" line and hand itself the one label the
rubric treats as authorising. A role that is a JSON field cannot be forged by the text in
the field beside it. Both fences share one nonce and one preamble, so the reviewer is told
the rule once and can still see where each block begins.

**Degradation is fail-closed and lives at the caller.** This module returns ``None`` for
every failure it can have — no model bound, a timeout, an unparseable answer — and never
a lenient verdict standing in for one. What ``None`` *means* is ``decide.py``'s to say,
and it says park.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings

from core.untrusted import new_nonce, untrusted_fence, untrusted_preamble
from prompts.utility import COMPACT_MARKER, REVIEW_INSTRUCTIONS
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
class TranscriptEntry:
    """One turn of the conversation as the reviewer may read it.

    A role and a text, kept apart, because the prompt renders them as JSON: the label is a
    field the message's own text cannot reach, which is the whole difference between "the
    operator said this" and "something claims the operator said this".
    """

    role: Literal["operator", "assistant"]
    text: str


@dataclass(frozen=True)
class ReviewRequest:
    """What a reviewer is given: an action's worst case, and the thread that led to it."""

    capability: Capability
    #: The recent conversation, already filtered to user and assistant prose
    #: (:func:`review_transcript`). Empty is legitimate — a stateless turn has no thread.
    transcript: Sequence[TranscriptEntry] = ()


#: The stage as a function, so the engine holds a reviewer rather than a model and a test
#: can substitute one without a model at all. Returns None on any failure (see the module
#: docstring); the caller turns that into a park.
type Reviewer = Callable[[ReviewRequest], Awaitable[ReviewVerdict | None]]


def review_transcript(
    messages: Sequence[ModelMessage],
    *,
    limit: int = TRANSCRIPT_MESSAGES,
    chars: int = MESSAGE_CHARS,
) -> tuple[TranscriptEntry, ...]:
    """The thread as the reviewer may see it: the operator's requests and the assistant's
    prose, in order, and nothing else.

    Four kinds of part are dropped and each for its own reason. **Tool returns** are
    content from outside the conversation and are the injection vector this whole design
    is arranged around. **Tool calls** are the model's own requests, and the one being
    judged is already described far more precisely by its capability. **Thinking** is the
    model's private argument for what it is about to do, which is exactly the material a
    reviewer should not be weighing when deciding whether the *operator* asked for it.
    And a **compaction summary** is a user-shaped message the operator never wrote: a
    utility model's fold of the earlier thread, tool returns included, which would
    otherwise carry every one of them back in wearing the operator's own role.
    """
    entries: list[TranscriptEntry] = []
    for message in list(messages)[-limit:]:
        if isinstance(message, ModelRequest):
            text = "\n".join(
                _prompt_text(part)
                for part in message.parts
                if isinstance(part, UserPromptPart) and not _is_compaction_summary(part)
            ).strip()
            if text:
                entries.append(TranscriptEntry("operator", text[:chars]))
        elif isinstance(message, ModelResponse):
            text = "\n".join(
                part.content for part in message.parts if isinstance(part, TextPart)
            ).strip()
            if text:
                entries.append(TranscriptEntry("assistant", text[:chars]))
    return tuple(entries)


def _is_compaction_summary(part: UserPromptPart) -> bool:
    """Whether this user-shaped message is a compaction checkpoint rather than a request.

    Recognised by the **first line** of the label the compaction writes in front of it,
    which is the same string the operator's transcript and the run's own event use — a
    marker, not a heuristic. Matching the marker rather than the whole preamble is what
    keeps a checkpoint stored before the preamble grew its second line recognisable. An
    operator who types that line themselves loses their message from the reviewer's view,
    which costs them a park and nothing else.
    """
    return _prompt_text(part).lstrip().startswith(COMPACT_MARKER)


def _prompt_text(part: UserPromptPart) -> str:
    """A user part's words. Multimodal content arrives as a list whose non-text items are
    binary — an image, a document — and have no place in a text transcript."""
    if isinstance(part.content, str):
        return part.content
    return "\n".join(item for item in part.content if isinstance(item, str))


def review_prompt(request: ReviewRequest) -> str:
    """The reviewer's one message: the structural facts, then everything anyone wrote.

    The split is by **author**, not by topic. What stands in the clear is what this
    process derived — the tool's name, the paths the grammar walk found, whether the
    action reaches the network, and what could not be read at all. What goes inside the
    fence is every byte a model produced: the action's summary (which, for a shell action,
    is the command) and the conversation. Putting the command in the clear was the older
    shape and the wrong one — a command is a string the model chose, and a reviewer
    reading it in the clear is reading instructions from the thing it is reviewing.

    The facts are JSON-encoded even though the *labels* are ours to trust, because their
    values are not: a path is a word the model wrote, and a word with a newline in it
    could otherwise write a line of its own. That covers the tool's own name too — an
    operator's MCP server names its tools, not this catalog.
    """
    capability = request.capability
    lines = [f"Tool: {json.dumps(capability.tool)}"]
    for label, values in (
        ("Reads", capability.reads),
        ("Writes", capability.writes),
        ("Sets in the environment", capability.env_writes),
        ("Reaches outside the workspace", capability.escapes),
        ("Could not be fully read", capability.unbounded),
    ):
        if values:
            lines.append(f"{label}: {json.dumps(list(values))}")
    lines.append(f"Reaches the network: {'yes' if capability.network else 'no'}")

    # One nonce and one preamble across both fences: the rule is the same rule, and the
    # reviewer that has been told it once does not read it better for being told twice.
    nonce = new_nonce()
    lines += ["", untrusted_preamble(nonce), "", "The action, as the model described it:"]
    lines.append(
        untrusted_fence(
            json.dumps({"summary": capability.summary}), nonce, source="tool-call"
        )
    )
    lines.append("")
    if request.transcript:
        conversation = [{"role": entry.role, "text": entry.text} for entry in request.transcript]
        lines.append("The conversation so far, oldest first:")
        lines.append(untrusted_fence(json.dumps(conversation), nonce, source="conversation"))
    else:
        lines.append("There is no conversation to read: the operator has said nothing.")
    return "\n".join(lines)


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

    The agent and its settings are built **here** rather than inside the closure. Nothing
    about either varies per call, and building an agent means deriving a JSON schema from
    :class:`ReviewVerdict` — paid once per reviewer, where one reviewer already serves a
    whole batch of deferred calls (``agent/gating.py``), instead of once per call.
    """
    agent = Agent(model, output_type=ReviewVerdict, instructions=REVIEW_INSTRUCTIONS)
    settings: ModelSettings = {
        "max_tokens": max_tokens,
        "temperature": 0.0,
        **(model_settings or {}),
    }

    async def review(request: ReviewRequest) -> ReviewVerdict | None:
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
