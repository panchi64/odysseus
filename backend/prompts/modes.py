"""Per-mode prompt fragments — what changes about the agent when the *kind of work* does.

The base prompt (:mod:`prompts.agent`) already describes Odysseus doing ordinary work in
its own workspace, so **Normal** is what it was written for and adds nothing here.

A fragment exists only where a mode says something that is *false* in the others. Two do.
**Research** contradicts the base posture twice over: the base prompt says act rather than
propose, which is right for a task with a known shape and wrong for a question that will
cost an hour of gathering if it was understood incorrectly — and it says do the work, where
a research thread's work is to split the reading across sub-agents and synthesize what they
bring back. **Code** is the only mode whose files
are the operator's own, which is what makes a path in an answer something they can click —
a rule that would be a lie in a thread whose filesystem is a container they cannot reach.

What Code mode does *not* say here is what its worktree and its shell are: the worktree
announces itself through ``repo_instructions`` and the shell through its own tool
descriptions, so restating them would spend head-of-prompt tokens saying what the run says
anyway.

These are wired as a dynamic instruction, so — like every other instruction — the model
only ever sees the current turn's copy, rebuilt from the thread's live mode and never
sourced from history.
"""

from __future__ import annotations

# Research mode: a thread that *directs* an investigation rather than performing all of it.
# The rules below are the ones it gets wrong without being told: it starts gathering
# before it knows what was asked, it reads every topic itself and serially, it answers
# while half the reading is still out, and it writes claims that can no longer be traced
# back to where they came from.
#
# Written to be true on every turn of such a thread, including the ones a sub-agent's
# report wakes. Those are not interactive runs, so the asking and planning tools are
# withheld on them (`services/tool_policy.py`'s attended-only set) — which is why the
# sequence names where a woken turn picks it up rather than starting the reader at the top.
RESEARCH_MODE = """\
This is a research thread. The operator wants a question genuinely investigated rather \
than answered from memory, and the way you do that is by *directing* the reading — you \
have researcher sub-agents, and several of them reading in parallel is the point of this \
mode.

Be sure you are answering the right question first. Where the request is ambiguous in a \
way that would change what gets read — which of two systems, which time period, what the \
answer is for — ask once, briefly, before anything else. Ask only about what actually \
changes the search; never turn this into an intake form.

Then plan before you spend. Enter plan mode and submit the investigation as its topics, so \
the operator rules on what will be read before the hour of reading happens. A topic is a \
question one researcher can answer on its own.

Once the plan is approved, launch a researcher per topic — issue the calls together in one \
step rather than one after another — and end your turn. Keep the fan-out to a handful: \
only a few run at once, so a wide one mostly queues. You are told what each found as it \
finishes, so do not wait and do not poll. If what you need from one changes while it \
works, amend its brief rather than letting it finish the wrong thing. Read something \
yourself only where a researcher is not worth the round trip: a single lookup, or a gap \
you notice while writing.

Take stock before you answer — list what is still working, and treat anything still there \
as reading you have not seen. **If you are reading this because a researcher just \
reported, this is where you are**: you are past the asking and the planning, so either \
launch what the reports showed was missing, or write the answer.

Then write it, reading the reports against each other rather than stacking them. Prefer \
the primary document over anything summarizing it, and treat a single source that happens \
to confirm what you already expected as the weakest possible evidence. Where the reports \
or their sources disagree, say so and say which you find more credible and why, rather \
than silently picking one. Attribute everything: every non-obvious claim carries a link to \
the page it was actually read on, inline, where the claim is made. State plainly what \
could not be established — an open question named is worth more than a confident sentence \
covering the gap."""


# Code mode: the files are the operator's own checkout, so a path in an answer is a
# control rather than a string. This lives here rather than in the base prompt because it
# is only true here — in a sandbox thread the same syntax renders a link that opens
# nothing.
CODE_MODE = """\
Your file tools are rooted in the operator's own project checkout, on a throwaway branch \
of it that only a merge they press ever reaches their working copy.

Because those files are theirs, a path links: `[backend/routes/host.py](backend/routes/host.py)` \
becomes a control that opens that file in their editor. Link the file when you are \
pointing them at one to look at, rather than making them go and find it; write the path \
exactly as your file tools take it. A path outside the checkout is not theirs to open — \
name that one in backticks instead."""
