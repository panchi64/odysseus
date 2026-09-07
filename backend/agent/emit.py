"""What a capability says on the operator's stream.

The two capabilities this codebase registers both observe a request as it is assembled —
what it weighs (``agent/overhead.py``) and which named contributor put what in front of
the model (``agent/injections.py``). Both then have to get their finding *out*, and until
Pydantic AI grew an event seam the only way was to reach through ``ctx.deps`` for the
``Run``. That made a capability — a library-owned hook, reusable by construction —
depend on our deps object, and every hook had to guard the reach in case an agent was
built without them.

Now the hook awaits ``ctx.emit`` and the event arrives in ``agent/translate.py``'s node
walk like any other, at the head of the request stream it was measured from, where it is
translated to our wire protocol in the one place that already does that translation.

**A capability's family is not a tool's.** Application code emits a ``CustomEvent`` (see
``tools/emit.py``); a capability hook emits a ``CapabilityEvent``, and emitting the wrong
family raises. That — plus the layer map, which puts ``tools`` *below* ``agent`` — is why
the two wrappers live in two files rather than one.

**And why ``runs`` does not simply subclass these.** ``runs/`` has no ``pydantic_ai``
import and should keep it that way: it is the protocol the frontend reads, and the day it
inherits from the engine is the day the wire contract moves when the engine does. The
dependency points this way — the agent layer knows about both — and not back.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel
from pydantic_ai import CapabilityEvent

from runs import TurnOverhead

#: Namespace for every capability event this codebase defines. The library requires one
#: and uses it to prefix the event's kind (``odysseus.chassis_event``), which is what
#: keeps our events distinguishable from a harness capability's on a shared stream.
NAMESPACE = "odysseus"


@dataclass(kw_only=True)
class ChassisEvent(CapabilityEvent, namespace=NAMESPACE):
    """A ``runs.events`` body a capability put on the stream.

    One wrapper rather than an event class per message, for the reason
    ``tools/emit.py``'s twin gives: ``runs/events.py`` already *is* the wire contract.
    """

    body: BaseModel


@dataclass(kw_only=True)
class OverheadMeasured(CapabilityEvent, namespace=NAMESPACE):
    """What the request about to go out carries besides the conversation.

    Not a ``runs.events`` body: this is state the run holds for the rest of the turn
    (``Run.context_overhead``, which the metrics frame reads at step end), not something
    the operator is shown as it happens. It rides the stream anyway so the capability
    that measures it needs nothing but the run context — the translator is what knows
    there is a ``Run`` to write it to.

    Default dispatch is enough: a capability event emitted from ``before_model_request``
    is delivered at the head of that request's stream, well before the step ends and the
    frame is built.
    """

    overhead: TurnOverhead
