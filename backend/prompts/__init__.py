"""The prompt library — every standing instruction we hand an LLM, in one place.

A prompt is product behavior, not an implementation detail: the words below are
what make the agent *act like Odysseus* turn after turn, so they live together
where they can be read, diffed, and tuned as a set rather than scattered as
inline string literals across the modules that happen to call a model.

Two domains:

- :mod:`prompts.agent` — the **main agent**: its ``SYSTEM_PROMPT`` (identity and
  voice, anchored in history) and ``INSTRUCTIONS`` (autonomy, tool posture, and
  safety guardrails, re-asserted fresh every turn), plus the verifier's nudge.
- :mod:`prompts.utility` — the cheap background calls (the thread **namer**, the
  deliverable **judge**) that run on the utility model.

Prompts are plain Python string constants so callers compose them the same way
they compose any other value (``.format(...)`` for the templated ones). Import
the specific constant — ``from prompts.agent import INSTRUCTIONS`` — rather than
reaching through this package.
"""

from __future__ import annotations

from .agent import INSTRUCTIONS, SYSTEM_PROMPT, VERIFIER_NUDGE
from .utility import JUDGE_INSTRUCTIONS, TITLE_INSTRUCTIONS

__all__ = [
    "INSTRUCTIONS",
    "JUDGE_INSTRUCTIONS",
    "SYSTEM_PROMPT",
    "TITLE_INSTRUCTIONS",
    "VERIFIER_NUDGE",
]
