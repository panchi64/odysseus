"""The deep-research feature (`DR-*`) — its surface, and how a research Run settles.

The pipeline core lives in `research/`; the clarify/plan REST exchange and the
start/finalize flow in `routes/research.py`. This manifest contributes the two
terminal-transition pieces: the waiter future the start route's finalize task
awaits, and the research-shaped notification policy (a conversation-less run that
is still worth announcing).
"""

from __future__ import annotations

import asyncio
import logging

from core.api_scopes import ScopeClaim
from harness.manifest import FeatureManifest, FeatureRuntime, HarnessContext
from routes import research as research_routes
from routes.deps import OPERATOR_ID
from runs import Run, RunStatus
from services.corpus import CorpusIndex, StubSurfaceAdapter
from services.notifications import NotificationService

logger = logging.getLogger(__name__)


async def _build(ctx: HarnessContext) -> FeatureRuntime:
    notifications = ctx.services.get(NotificationService)
    # Research is a planned corpus surface: a stub row until its extraction
    # pipeline lands, so the /rag list shows the whole picture from day one.
    ctx.services.get(CorpusIndex).register(
        StubSurfaceAdapter("surf-research", "Research", "research", "/research")
    )

    # Keyed by run id — `routes/research.py`'s `start` route registers one per
    # research Run it submits, and its own background finalize task awaits it to
    # learn the outcome to persist (report/stats/status). Kept separate from the
    # scheduler's bookkeeping so the two features never collide on a run id.
    run_waiters: dict[str, asyncio.Future[Run]] = {}

    def _resolve_waiter(run: Run) -> None:
        waiter = run_waiters.pop(run.id, None)
        if waiter is not None and not waiter.done():
            waiter.set_result(run)

    async def _notify_research_terminal(run: Run, watched: bool) -> None:
        """Research runs are conversation-less (no thread to deep-link to) but are
        their own noteworthy surface: unlike a chat turn, finishing is worth a
        notification even if the operator's tab was open and watching the live
        progress the whole time (they may well have navigated away for the several
        minutes a run takes). Cancelled stays silent (the operator asked for it);
        blocked never happens here (the pipeline never calls `run.block()`) but
        would fall through to silence too."""
        if run.kind != "research":
            return
        if run.status not in (RunStatus.done, RunStatus.error):
            return
        try:
            research_row = await research_routes.find_by_run(ctx.engine, run.id)
        except Exception:
            logger.exception(
                "notifications: failed to resolve research run %s at terminal", run.id
            )
            return
        if research_row is None:
            return
        question = ctx.vault.decrypt_str(research_row.question_enc)
        title = question if len(question) <= 80 else question[:79] + "…"
        if run.status is RunStatus.error:
            await notifications.notify(
                OPERATOR_ID,
                "run_failed",
                f'Research on "{title}" failed',
                body=run.error,
                run_id=run.id,
                research_id=research_row.id,
            )
        else:
            await notifications.notify(
                OPERATOR_ID,
                "run_completed",
                f'Research on "{title}" is ready',
                run_id=run.id,
                research_id=research_row.id,
            )

    return FeatureRuntime(
        state={"research_run_waiters": run_waiters},
        run_terminal_sync=(_resolve_waiter,),
        run_terminal=(_notify_research_terminal,),
    )


MANIFEST = FeatureManifest(
    name="research",
    after=("corpus", "notifications"),
    routers=(research_routes.router,),
    api_scopes=(ScopeClaim("research", ("/research",)),),
    build=_build,
)
