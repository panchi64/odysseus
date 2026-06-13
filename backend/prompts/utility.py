"""Background-call prompts — the cheap utility-model work that runs around a turn,
never as the operator-facing voice.

These are deliberately narrow, single-purpose instructions: each drives a one-shot
``make_utility_agent`` call (see :mod:`agent.meta`) whose output is consumed by the
chassis, not shown verbatim. Keep them strict and unembellished — a utility prompt
that editorializes makes its output harder to use.
"""

from __future__ import annotations

# Names a fresh conversation from the user's opening message. Output is the title
# itself, nothing else — the caller strips stray quotes/prefixes but expects clean
# input. The title reflects what the user asked, never the assistant's reply.
TITLE_INSTRUCTIONS = (
    "You name chat threads. Given a user's opening message, reply with a short, "
    "specific title of 3-6 words that captures their topic or request in Title "
    "Case. Output only the title: no quotes, no surrounding punctuation, no "
    "preamble, no explanation."
)

# The deliverable judge behind the verifier. Rules whether a turn actually did what
# was asked; its ``reason`` feeds the corrective nudge (``prompts.agent``), so it
# must be specific about what's missing.
JUDGE_INSTRUCTIONS = (
    "You verify whether an assistant's response fully satisfied the user's request. "
    "Be strict about concrete deliverables the user named. Set ok=false with a short, "
    "specific reason when something asked for is missing or wrong; otherwise ok=true."
)
