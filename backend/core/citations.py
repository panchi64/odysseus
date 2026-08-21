"""Sources a tool result carries.

Some tool results are *about* places on the web — a search's hits, a fetched page — and
the run stream surfaces those as citations so the answer can show its sources. The
question is who knows which results those are.

Not the event translator. It sits in Pillar II, turning the library's run into our
protocol, and a translator that matches on ``"web_search"`` and imports
``services.search`` has to be edited every time a feature grows a tool that cites
something — and knows about a feature's own types to do it. So the result type declares
its own sources instead: anything with a ``citations()`` method is citable, and the
translator asks rather than recognizes.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class Citation:
    """One source a tool result points at. Deliberately not the wire event: this is what
    a capability declares, and the run stream decides how to frame it."""

    url: str
    title: str | None = None


@runtime_checkable
class Citable(Protocol):
    """A tool result that names the sources behind it.

    Order matters — it is the order the sources are surfaced in. Dedup and numbering are
    the consumer's concern (the run's citation fold dedups by URL, the Sources row numbers
    by position), so an implementation returns what it found and nothing more.
    """

    def citations(self) -> Sequence[Citation]: ...
