"""What a model request carries besides the conversation.

Sits in ``runs`` rather than beside the code that measures it (``agent.overhead``) for
the same reason ``runs.timings`` does: the :class:`Run` holds one across a turn, and
``runs`` cannot import from ``agent``. The measurement is the agent layer's; the value
is the run's.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TurnOverhead:
    """The standing brief and the tool schemas, in characters.

    Characters rather than tokens because these are only ever used as proportions
    against the message estimate (``services.context_budget``), and rounding each to
    tokens before comparing them would throw away precision for nothing.

    ``system`` is the instructions and the system prompt as one figure. They are separate
    mechanisms — instructions are re-sent every turn and never retained in history, a
    system prompt is retained — but they are one thing to the operator, the standing
    brief, and splitting a readout by an internal distinction nobody outside this
    codebase can act on is detail for its own sake.

    ``tools`` is every tool name, description and JSON schema the model was handed. This
    is the part most operators have never seen a number for, and the one most often
    responsible for a window that feels full before the conversation has said anything.
    """

    system: int
    tools: int
