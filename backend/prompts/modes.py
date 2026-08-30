"""Per-mode prompt fragments — what changes about the agent when the *kind of work* does.

The base prompt (:mod:`prompts.agent`) already describes Odysseus doing ordinary work in
its own workspace, so most modes add nothing here. **Normal** is what the base prompt was
written for. **Code** differs in its filesystem and its tools, and both of those already
announce themselves — the worktree through ``repo_instructions``, the shell through its
own tool descriptions — so restating them in prose would only spend head-of-prompt tokens
saying what the run says anyway.

A fragment exists only where a mode genuinely *contradicts* the base posture. Research is
the one that does: the base prompt says act rather than propose, which is right for a task
with a known shape and wrong for a question that will cost an hour of gathering if it was
understood incorrectly.

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
