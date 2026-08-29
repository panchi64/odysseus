"""What a model request carries besides the conversation.

Sits in ``runs`` rather than beside the code that measures it (``agent.overhead``) for
the same reason ``runs.timings`` does: the :class:`Run` holds one across a turn, and
``runs`` cannot import from ``agent``. The measurement is the agent layer's; the value
is the run's.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BriefBlock:
    """One contributor to the standing brief, in characters.

    ``id`` is a stable slug the readout groups by — ``base`` for the fixed prompt this
    codebase always sends, and one per dynamic instruction provider (the skill catalog,
    the project's own instruction files, the delegate listing), derived from the
    provider's own name. The operator-facing wording is the client's; what travels is
    which block it was.
    """

    id: str
    chars: int


@dataclass(frozen=True)
class ToolGroupOverhead:
    """One tool category's share of the schemas, in characters, and how many tools it
    put there.

    The category is the namespace prefix the tool was registered under
    (``tools/toolsets.py`` builds every name as ``category_tool``), so this is the same
    grouping the operator's own tool settings page uses — which is the point: a category
    that is eating the window is a category they can switch off in one place.
    """

    category: str
    tools: int
    chars: int


@dataclass(frozen=True)
class TurnOverhead:
    """The standing brief and the tool schemas, in characters.

    Characters rather than tokens because these are only ever used as proportions
    against the message estimate (``services.context_budget``), and rounding each to
    tokens before comparing them would throw away precision for nothing.

    ``system`` is the whole standing brief as one figure and ``tools`` every tool name,
    description and JSON schema the model was handed. ``blocks`` and ``groups`` are the
    same two numbers itemised — they sum to their totals by construction, and the totals
    stay because they are what the gauge's three-part bar is drawn from.

    The itemisation is what makes the readout *actionable* rather than merely accurate:
    "your brief is 5k" is a fact, "the skill catalog is 4k of it" is a decision. Both
    default to empty, so a measurement that could only reach the totals (an older
    cached one, a library upgrade that moved an internal) still reports them.
    """

    system: int
    tools: int
    blocks: tuple[BriefBlock, ...] = ()
    groups: tuple[ToolGroupOverhead, ...] = ()
