"""The `research` category — deep research, started on the operator's behalf.

Two tools, and the shape of them is the whole design.

**`start` does not wait.** A research run takes minutes and is its own Run on the same
substrate; blocking the chat turn on it would spend the turn's entire step budget
watching a progress bar, and a disconnect would strand it. So `start` returns the moment
the run is submitted, and the tool result says so in words — otherwise the model sits
and polls, which is the same waste one level up.

**`start` is approval-gated.** It spends real model budget and reaches the open web
unattended, which is exactly the shape of thing the operator should see before it
happens. The question rides on the approval prompt, so what is being researched is what
they are approving; a conversation-scoped grant stops them being asked every time.

**`read` is not gated.** It reads back an entry the operator can already see on the
Research surface.
"""

from __future__ import annotations

from pydantic_ai import FunctionToolset, ModelRetry, RunContext

from services.research_launcher import ResearchLauncher, ResearchUnavailableError
from tools.deps import RunDeps

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
        Tell the operator it is running and that they will be notified when the report
        is ready — they can watch it on the Research page meanwhile. Use ``research_read``
        later (in a subsequent turn, if they ask) to read the finished report.

        ``question`` is the research question, stated in full.
        ``context`` is what this conversation has already established that narrows it —
        constraints, what has been ruled out, what the operator actually wants from it.
        It replaces the clarifying questions the operator would otherwise be asked.
        """
        launcher = ctx.deps.caps.get_optional(ResearchLauncher)
        if launcher is None:
            return {"started": False, "detail": _UNAVAILABLE}
        try:
            launched = await launcher.launch(ctx.deps.owner_id, question, context)
        except ResearchUnavailableError as exc:
            # A state the system is in, not a bug — hand it back so the model can adapt
            # (fall back to web_search, or tell the operator what to switch on).
            return {"started": False, "detail": str(exc)}
        return {
            "started": True,
            "research_id": launched.research_id,
            "run_id": launched.run_id,
            "question": launched.question,
            "detail": (
                "Research is running in the background and will take several minutes. "
                "Do not wait for it. The operator is notified when it finishes; read it "
                "later with research_read using this research_id."
            ),
        }

    @toolset.tool(name="read")
    async def read_research(ctx: RunContext[RunDeps], research_id: str) -> dict:
        """Read a research entry — its status, and the full report once it has finished.

        A `running` status means it is still working; say so rather than calling this
        again in a loop.
        """
        launcher = ctx.deps.caps.get_optional(ResearchLauncher)
        if launcher is None:
            return {"available": False, "detail": _UNAVAILABLE}
        try:
            snap = await launcher.snapshot(ctx.deps.owner_id, research_id)
        except ResearchUnavailableError as exc:
            # Recoverable: the model very likely mistyped or invented the id, and should
            # pick another path rather than fail the turn.
            raise ModelRetry(str(exc)) from exc
        return {
            "available": True,
            "research_id": snap.research_id,
            "question": snap.question,
            "status": snap.status,
            "sources": snap.sources,
            "findings": snap.findings,
            "report": snap.report,
        }

    return toolset
