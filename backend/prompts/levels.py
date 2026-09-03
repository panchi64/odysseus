"""Per-level prompt fragments — what the model is told about how far it may go.

A thread's permission level is enforced whether or not the model knows about it: Plan is
enforced by *absence* (the mutating tools are never offered), Manual and Edit by a park,
Auto by a review. So a fragment here buys nothing in safety — it buys the model an
explanation for what it is about to experience.

That matters at exactly three levels. At **Plan** the base instruction to act rather than
propose is the wrong posture, and a model that does not know why its tools are missing
reads a deliberately narrowed catalog as a broken installation and says so. At **Manual**
every change stops on the operator, so how the work is *shaped* changes: ten separate
edits are ten interruptions, and the model is the only thing that can group them. At
**Auto** there is one thing the model is asked to *state* rather than merely do — the
reach a command needs — and a declaration nothing explained would be filled in by guess.

**A fragment is delivered at its level in every mode, so it may claim nothing about the
catalog.** The tools that take a ``reach`` are the shell's, and the shell is code mode's
alone (``services/modes.MODE_SCOPED_TOOLS``); Auto is now every fresh thread's level, so a
sentence beginning "every shell command" would be a false premise on the majority of
threads, about tools they were never offered. It is written as the conditional it actually
is — *where* a tool asks how far a command reaches — which costs a clause and is true
everywhere the fragment is delivered.

**Edit says nothing.** It is the level the base prompt was written for — act, the approval
gate catches what is genuinely dangerous — and repeating that here would spend
head-of-prompt tokens agreeing with the paragraph above it. Restating a rule is not
reinforcing it; it is diluting the one place it is stated.

Wired as a dynamic instruction, so — like every other instruction — the model only ever
sees the current turn's copy, rebuilt from the thread's live level and never sourced from
history. A level the operator changes mid-thread therefore takes effect on the next turn
with no history to contradict it.
"""

from __future__ import annotations

# Plan: read-only by construction. The second sentence is the load-bearing one — without
# it the model spends the turn hunting for a tool that was withheld on purpose, or reports
# the gap as a fault.
PLAN_LEVEL = """\
This thread is at the Plan level: read and search, but change nothing. Work out what you \
would do and propose it, concretely enough that the operator can accept it and have it \
carried out — which files, which commands, what would change. A tool you would need in \
order to act is absent on purpose, not missing; say what you would have used it for \
rather than looking for another way around."""


# Manual: the level where the model's own batching decides how many times the operator is
# interrupted. Nothing else in the brief tells it that, because at every other level it is
# not true.
MANUAL_LEVEL = """\
This thread is at the Manual level: every change pauses for the operator's approval before \
it happens. Work in whole steps rather than small ones — group related changes into a \
single call, and related calls into a single stretch, so they approve one coherent piece \
of work instead of a dozen fragments of it."""


# Auto: the level where the approvals are given for the model, by a review it never sees
# the rules of. Only two things here are the model's to act on — declare the reach, and
# prefer the contained approach — and both are said in the plainest way available. The
# review's own rubric is deliberately not restated: a model told what clears the bar writes
# for the bar rather than writing the truth, which is the same reason the reviewer is never
# told the passing combination either (`prompts/utility.py`).
AUTO_LEVEL = """\
This thread is at the Auto level: a review decides in the operator's place, and only what \
it will not settle stops for them. Work that stays inside this workspace and reaches no \
network is settled without asking anyone, so prefer the approach that stays there. Where \
a tool asks how far a command needs to reach, answer it honestly — that declaration is \
what the sandbox around the command is built from, and one that needs more than it \
declared fails inside that sandbox rather than going ahead. Anything reaching the network \
is reviewed, and anything whose effect could not be undone stops for the operator however \
plainly it was asked for."""
