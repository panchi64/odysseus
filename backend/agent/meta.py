"""The meta-loop — what we own *around* the agent's within-turn reasoning.

Two independent mechanisms:

- :class:`LoopBreaker` is **always on**. It watches the tool calls a turn makes
  and aborts when the agent repeats an identical call instead of converging — a
  no-progress guard the model can't talk its way past.
- The **verifier** is opt-in. After a turn produces an answer, a judge (the
  utility model, or an injected stub) decides whether the request was actually
  satisfied; if not, the engine makes a single bounded corrective re-attempt.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel


class LoopDetected(Exception):
    """Raised when a turn repeats an identical tool call without progressing."""

    def __init__(self, tool_name: str) -> None:
        super().__init__(f"repeated the same call to {tool_name!r} without progress")
        self.tool_name = tool_name


class LoopBreaker:
    """Counts identical tool calls within a turn; trips at a repeat threshold."""

    def __init__(self, *, repeat_threshold: int = 3) -> None:
        self._counts: dict[tuple[str, str], int] = {}
        self._threshold = repeat_threshold

    def check(self, name: str, args: dict[str, Any]) -> None:
        """Record a tool call; raise :class:`LoopDetected` once it repeats too often."""
        signature = (name, json.dumps(args, sort_keys=True, default=str))
        self._counts[signature] = self._counts.get(signature, 0) + 1
        if self._counts[signature] >= self._threshold:
            raise LoopDetected(name)


class Verdict(BaseModel):
    """A judge's call on whether a response satisfied the request."""

    ok: bool
    reason: str = ""


# A judge inspects (request, answer) and rules on whether the task was done.
Judge = Callable[[str, str], Awaitable[Verdict]]


_JUDGE_INSTRUCTIONS = (
    "You verify whether an assistant's response fully satisfied the user's request. "
    "Be strict about concrete deliverables the user named. Set ok=false with a short, "
    "specific reason when something asked for is missing or wrong; otherwise ok=true."
)


async def utility_judge(request: str, answer: str) -> Verdict:
    """The default judge — asks the utility model whether the task was satisfied."""
    from pydantic_ai import Agent

    from services import llm

    judge = Agent(
        llm.resolve_model("utility"), output_type=Verdict, instructions=_JUDGE_INSTRUCTIONS
    )
    result = await judge.run(f"Request:\n{request}\n\nResponse:\n{answer}")
    return result.output
