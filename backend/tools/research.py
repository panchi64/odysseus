"""The `research` category — deep research, started on the operator's behalf.

Two tools, and the shape of them is the whole design.

**`start` does not wait.** Research takes minutes and runs as its own Run on the same
substrate; blocking the chat turn on it would spend the turn's entire step budget
watching a progress bar, and a disconnect would strand it. So `start` returns the moment
the run is submitted, and the tool result says so in words — otherwise the model sits
and polls, which is the same waste one level up.

**`start` is marked sensitive.** It spends real model budget and reaches the open web
unattended, which is exactly the shape of thing the operator should see before it
happens. The question rides on the approval prompt, so what is being researched is what
they are ruling on; a conversation-scoped grant stops them being asked every time.

**`read` is not.** It reads back a conversation the operator can already open.

What changed underneath, and why the signatures did not: research used to be a pipeline
with its own store and its own report, and is now a linked **conversation in research
mode**. From the model's side that is the same two verbs over the same two nouns — a
question goes in, an answer comes back later — so the tools kept their names and their
descriptions, and only their bodies moved. What the operator gets is different in the way
that matters: a thread they can open, read, question and continue, rather than a report
that arrives finished.
"""

from __future__ import annotations

from pydantic_ai import FunctionToolset, ModelRetry, RunContext

from runs import ConversationLinked
from services.research_threads import (
    ParentThread,
    ResearchThreads,
    ResearchUnavailableError,
)
from tools.deps import RunDeps
from tools.workspace import run_workspace

_UNAVAILABLE = "Deep research is unavailable in this deployment."


def research_toolset() -> FunctionToolset[RunDeps]:
    toolset = FunctionToolset[RunDeps]()

    @toolset.tool(name="start", requires_approval=True)
    async def start_research(
        ctx: RunContext[RunDeps], question: str, context: str = ""
    ) -> dict:
        """Start a deep-research run on the operator's behalf.

        Use this for a question that genuinely needs multi-round investigation across
        many web sources — not for something a single ``web_search`` answers.

        It returns **immediately**, as soon as the run is submitted. The research then
        takes several minutes on its own; do not wait for it and do not poll in a loop.
        Tell the operator it is running and that they will be notified when it settles —
        it is a thread of its own, which they can open and read meanwhile. Use
        ``research_read`` later (in a subsequent turn, if they ask) to read what it found.

        ``question`` is the research question, stated in full.
        ``context`` is what this conversation has already established that narrows it —
        constraints, what has been ruled out, what the operator actually wants from it.
        It replaces the clarifying questions the operator would otherwise be asked.
        """
        threads = ctx.deps.caps.get_optional(ResearchThreads)
        if threads is None:
            return {"started": False, "detail": _UNAVAILABLE}
        try:
            started = await threads.start(
                ctx.deps.owner_id,
                question,
                context=context,
                parent=await _parent(ctx),
            )
        except ResearchUnavailableError as exc:
            # A state the system is in, not a bug — hand it back so the model can adapt
            # (fall back to web_search, or tell the operator what to switch on).
            return {"started": False, "detail": str(exc)}
        # The operator's own record that this turn spawned something: the new thread is
        # about to appear in their session list, and without this it would appear with no
        # explanation of where it came from.
        ctx.deps.run.emit(
            ConversationLinked(
                conversation_id=started.conversation_id,
                relation="research",
                title=started.question,
            )
        )
        return {
            "started": True,
            "conversation_id": started.conversation_id,
            "run_id": started.run_id,
            "question": started.question,
            "detail": (
                "Research is running in its own thread and will take several minutes. "
                "Do not wait for it. The operator is notified when it settles; read it "
                "later with research_read using this conversation_id."
            ),
        }

    @toolset.tool(name="read")
    async def read_research(ctx: RunContext[RunDeps], conversation_id: str) -> dict:
        """Read a research thread — its status, and what it has answered so far.

        A `running` status means it is still working; say so rather than calling this
        again in a loop.
        """
        threads = ctx.deps.caps.get_optional(ResearchThreads)
        if threads is None:
            return {"available": False, "detail": _UNAVAILABLE}
        try:
            view = await threads.read(ctx.deps.owner_id, conversation_id)
        except ResearchUnavailableError as exc:
            # Recoverable: the model very likely mistyped or invented the id, and should
            # pick another path rather than fail the turn.
            raise ModelRetry(str(exc)) from exc
        return {
            "available": True,
            "conversation_id": view.conversation_id,
            "question": view.question,
            "status": view.status,
            "answer": view.answer,
        }

    return toolset


async def _parent(ctx: RunContext[RunDeps]) -> ParentThread:
    """What the calling thread hands the new one.

    The seeding rule is the reason this is not just an id: a **code** thread's research
    must read a *copy* of the worktree, never the operator's own working tree, because
    the two threads would otherwise be editing and analysing the same checkout at the
    same time. The parent's workspace is already resolved (and memoised) for this run, so
    naming its directory here costs nothing; a sandbox thread seeds nothing, because its
    container is not the operator's anything.

    The parent's permission level rides along for a related reason: the operator approved
    *this* thread at *that* level, and the thread it opens must not quietly come up with
    more rope than the one that asked for it.
    """
    seed_from = None
    try:
        workspace = await run_workspace(ctx)
    except Exception:
        # A workspace that will not open is a reason to start the thread empty, never a
        # reason to refuse the research.
        workspace = None
    if workspace is not None and workspace.kind == "worktree":
        seed_from = workspace.root
    return ParentThread(
        conversation_id=ctx.deps.conversation_id,
        project_id=ctx.deps.project_id,
        permission=ctx.deps.permission,
        seed_from=seed_from,
    )
