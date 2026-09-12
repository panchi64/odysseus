"""How a sub-agent's report is framed, and how that framing is read back.

Pydantic AI has one shape for a message from outside the model — ``UserPromptPart`` — so a
report rides into the launching thread as one. Left bare it would claim the operator typed
it: the model would answer as though they had, the transcript would show it as theirs, and
every later turn would replay it that way. So it is wrapped, once, here.

**One envelope, both roads.** A report reaches the thread two ways — queued into a turn
that is still running, or as the prompt of a turn it wakes — and the wording is identical,
because those are the same event and nothing downstream should be able to tell which route
it took.

**Two readers, one constant.** To the model the envelope is plain framing and nothing
parses it. Coming back out, the transcript recognises it and renders a report rather than
something the operator said. That reader matches the **whole** header this module writes —
opener *and* preamble — rather than the opening tag alone, because an operator can type
angle brackets and a message of theirs relabelled as a sub-agent's is the same lie in
reverse.

**It is a label, not a credential**, and nothing may come to depend on it as one: a text
marker is forgeable by anyone who can type it, and what a forgery buys is a differently
styled bubble in the forger's own thread. The load-bearing answer to "who sent this" is
``QueuedMessage.source``, which is structural and never arrives from outside.

It lives in ``services/`` rather than beside the injection point because both of those
readers are below the agent layer, and the alternative to one home is two copies of a
marker that only works while they agree.
"""

from __future__ import annotations

#: The opener the transcript matches on, and the closer that bounds the body.
REPORT_OPEN = "<subagent-report>"
REPORT_CLOSE = "</subagent-report>"

#: Said to the model, not to the operator. Deliberately explicit that they have not seen
#: this — a model that thanked them for the finding would be the first sign it had gone
#: wrong — and stripped back out before the transcript shows the report.
_PREAMBLE = (
    "A sub-agent you launched has finished and reported back. This is its report, not a "
    "message from the operator — they have not seen it and are not waiting on a reply to "
    "it. Carry on with whatever it unblocks, and tell them what matters."
)


#: The whole header, which is what a report is recognised by.
_HEADER = f"{REPORT_OPEN}\n{_PREAMBLE}\n\n"


def report_envelope(text: str) -> str:
    """A sub-agent's report, framed as one."""
    return f"{_HEADER}{text.strip()}\n{REPORT_CLOSE}"


def report_body(text: str) -> str | None:
    """The report inside an envelope, or ``None`` when this is not one."""
    stripped = text.strip()
    if not stripped.startswith(_HEADER):
        return None
    return stripped[len(_HEADER) :].removesuffix(REPORT_CLOSE).strip()
