"""How a message crossing the link between a thread and its sub-agent is framed.

Two messages cross it, in opposite directions: a **report** coming back when a sub-agent
finishes, and a **direction** going down when the launching agent redirects one that is
still working. Both are framed here, on one shape, because they have the same problem.

Pydantic AI has one shape for a message from outside the model — ``UserPromptPart`` — so a
report rides into the launching thread as one. Left bare it would claim the operator typed
it: the model would answer as though they had, the transcript would show it as theirs, and
every later turn would replay it that way. A direction has the mirror of that problem —
a sub-agent has no operator at all, so unframed text in its thread is from nobody. So both
are wrapped, once, here.

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

#: The same pair for the message travelling the other way down the link — the launching
#: agent redirecting a sub-agent that is still working.
DIRECTION_OPEN = "<subagent-direction>"
DIRECTION_CLOSE = "</subagent-direction>"

#: Said to the model, not to the operator. Deliberately explicit that they have not seen
#: this — a model that thanked them for the finding would be the first sign it had gone
#: wrong — and stripped back out before the transcript shows the report.
_REPORT_PREAMBLE = (
    "A sub-agent you launched has finished and reported back. This is its report, not a "
    "message from the operator — they have not seen it and are not waiting on a reply to "
    "it. Carry on with whatever it unblocks, and tell them what matters."
)

#: The mirror, read by the sub-agent rather than by the thread that launched it. Explicit
#: about all three things a sub-agent would otherwise get wrong here: who this is from,
#: that it supersedes rather than adds to the brief, and that answering it is not a thing —
#: nobody is reading the sub-agent's thread, and its one reply is the report it ends with.
_DIRECTION_PREAMBLE = (
    "The agent that launched you has sent you this. It is not from the operator, and it "
    "changes the task you were given — take it as amending your brief, and prefer it where "
    "the two disagree. Do not reply to it; carry on with the work and report as usual."
)


def _header(opener: str, preamble: str) -> str:
    """The whole header, which is what an envelope is recognised by — opener *and*
    preamble, never the tag alone. Anyone can type an opening tag, and a message
    relabelled as a sub-agent's is the same lie as a report relabelled as the
    operator's."""
    return f"{opener}\n{preamble}\n\n"


_REPORT_HEADER = _header(REPORT_OPEN, _REPORT_PREAMBLE)
_DIRECTION_HEADER = _header(DIRECTION_OPEN, _DIRECTION_PREAMBLE)


def _wrap(header: str, closer: str, text: str) -> str:
    return f"{header}{text.strip()}\n{closer}"


def _unwrap(header: str, closer: str, text: str) -> str | None:
    stripped = text.strip()
    if not stripped.startswith(header):
        return None
    return stripped[len(header) :].removesuffix(closer).strip()


def report_envelope(text: str) -> str:
    """A sub-agent's report, framed as one."""
    return _wrap(_REPORT_HEADER, REPORT_CLOSE, text)


def report_body(text: str) -> str | None:
    """The report inside an envelope, or ``None`` when this is not one."""
    return _unwrap(_REPORT_HEADER, REPORT_CLOSE, text)


def direction_envelope(text: str) -> str:
    """A launching agent's mid-flight redirection, framed as one."""
    return _wrap(_DIRECTION_HEADER, DIRECTION_CLOSE, text)


def direction_body(text: str) -> str | None:
    """The direction inside an envelope, or ``None`` when this is not one."""
    return _unwrap(_DIRECTION_HEADER, DIRECTION_CLOSE, text)
