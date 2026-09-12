"""How a message that is not the operator's reaches the model.

A sub-agent's report is delivered into the launching thread the same way an operator's
mid-turn message is — queued on the Run, handed over at the next model-request boundary.
That road is the right one and was chosen deliberately: the injection point amends the
*next, not-yet-sent* request, so nothing queued can interrupt a model that is mid-stream.

What it cannot do is let the two arrive looking the same. Pydantic AI has one shape for a
message from outside the model — ``UserPromptPart`` — so a report rides in as one, and
without a marker the transcript would claim the operator typed it, the model would answer
as though they had, and every later turn would replay it that way. So the text is wrapped,
once, here.

**A marker, not a protocol.** The envelope is plain text the model reads as framing; there
is no parser on the other side and nothing keys off it. The structured answer to "who said
this" is the ``source`` on the queued message and the ``origin`` on the persisted row —
this is what makes the *model's* copy honest, which those cannot.

The wrap happens at injection rather than at delivery so that one report is worded one way
wherever it came from: a report that woke a finished turn and a report that landed in a
running one are the same sentence.
"""

from __future__ import annotations

from runs import QueuedMessage

#: What a sub-agent's report is wrapped in. Deliberately unlike anything the operator would
#: type, and deliberately explicit that the operator has not seen it — a model that thanked
#: them for the finding would be the first sign this had gone wrong.
_REPORT = (
    "<subagent-report>\n"
    "A sub-agent you launched has finished and reported back. This is its report, not a "
    "message from the operator — they have not seen it and are not waiting on a reply to "
    "it. Carry on with whatever it unblocks, and tell them what matters.\n\n"
    "{text}\n"
    "</subagent-report>"
)


def injected_text(message: QueuedMessage) -> str:
    """One queued message as the model should read it.

    The operator's own words are handed over untouched: they are what a user message is,
    and wrapping them would put framing between the operator and the model that neither
    asked for.
    """
    if message.source == "subagent":
        return _REPORT.format(text=message.text.strip())
    return message.text
