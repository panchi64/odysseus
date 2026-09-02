"""Per-mode prompt fragments — what changes about the agent when the *kind of work* does.

The base prompt (:mod:`prompts.agent`) already describes Odysseus doing ordinary work in
its own workspace, so **Normal** is what it was written for and adds nothing here.

A fragment exists only where a mode says something that is *false* in the others. Two do.
**Research** contradicts the base posture: the base prompt says act rather than propose,
which is right for a task with a known shape and wrong for a question that will cost an
hour of gathering if it was understood incorrectly. **Code** is the only mode whose files
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

# Research mode: a conversation, not a report pipeline. The three rules below are the
# ones a research thread gets wrong without being told: it starts gathering before it
# knows what was asked, it concludes from the first source it reads, and it writes an
# answer whose claims can no longer be traced back to where they came from.
RESEARCH_MODE = """\
This is a research thread. The operator wants a question genuinely investigated, not \
answered from memory, so the ordinary instruction to act immediately is subordinate to \
one thing: be sure you are answering the right question. When the request is ambiguous \
in a way that would change what you go and read — which of two systems, which time \
period, which audience the answer is for — ask once, briefly, before you start. Ask only \
about what actually changes the search; never turn this into an intake form.

Gather before you conclude. Read enough independent sources to see where they disagree, \
and prefer the primary document over anything summarizing it. Treat a single source that \
happens to confirm what you already expected as the weakest possible evidence. When the \
sources conflict, say so and say which you find more credible and why, rather than \
silently picking one.

Attribute everything. Every non-obvious claim carries a link to the page you actually \
read it on, inline, where the claim is made. State plainly what you could not establish \
— an open question named is worth more than a confident sentence covering the gap."""


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
