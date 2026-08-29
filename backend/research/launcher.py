"""The agent-facing way to start a research run.

`routes/research_launch.py` is the operator's path: it reads a *draft* the operator has
already refined through the clarify exchange, and answers in HTTP. This is the agent's,
and the difference is what it has to supply for itself — there is no operator on the
other end of a clarifying question mid-turn, so the agent's own `context` argument
stands in for that exchange and the plan is produced in one step.

Everything after that is deliberately the same machinery: the same `run_research`
pipeline, submitted to the same Run substrate, recorded on the same `ResearchRun` row,
finalized by the same terminal hooks. A run the agent started is indistinguishable from
one the operator started once it is going — it appears on the Research surface, streams
on `/runs/{id}/events`, and notifies on completion. That is the point: this adds an
entry point, not a second implementation.

Implements the `services.research_launcher.ResearchLauncher` seam so `tools/research.py`
can resolve it without importing this layer (orchestrators sit above tools).
"""

from __future__ import annotations

import asyncio
import logging

from core.db import in_session
from core.vault import Vault
from models._fields import new_id, utcnow
from models.research import ResearchRun, ResearchStatus
from research.pipeline import run_research
from research.planning import produce_plan
from research.state import ResearchDeps
from routes import research_store
from routes.research_store import RunOutcome
from runs import Run, RunRegistry
from services import llm
from services.research_launcher import (
    LaunchedResearch,
    ResearchLauncher,
    ResearchSnapshot,
    ResearchUnavailableError,
)

logger = logging.getLogger(__name__)

# Deep research *is* outbound search plus browser fetch — every round gathers evidence
# that way and the pipeline has no other means. Mirrors the constant in
# `routes/research_launch.py` rather than importing it: both state what the pipeline
# needs, and neither should move because the other did.
_REQUIRED_WEB_TOOLS = frozenset({"web_search", "web_fetch"})

# Slack above the operator-configured limit for the Run's own wall-clock backstop. The
# pipeline enforces the real limit at round boundaries, but the final un-timed write-up
# runs after the loop breaks and must not be hard-cancelled mid-report.
_WALL_CLOCK_BUFFER_S = 180.0


class PipelineResearchLauncher(ResearchLauncher):
    """The real launcher, closing over everything a run needs.

    Constructed once by the research manifest, where all of these handles are already
    resolved — which is what lets a tool start a run without a `Request`.
    """

    def __init__(
        self,
        *,
        engine,
        vault: Vault,
        runs: RunRegistry,
        registry,
        search,
        fetcher,
        settings,
        run_waiters: dict[str, asyncio.Future[Run]],
        terminal_tasks: set[asyncio.Task],
        disabled_tools,
    ) -> None:
        self._engine = engine
        self._vault = vault
        self._runs = runs
        self._registry = registry
        self._search = search
        self._fetcher = fetcher
        self._settings = settings
        self._run_waiters = run_waiters
        self._terminal_tasks = terminal_tasks
        self._disabled_tools = disabled_tools

    async def launch(
        self, owner_id: str, question: str, context: str = ""
    ) -> LaunchedResearch:
        # Refuse rather than degrade. The pipeline treats a missing search capability as
        # "this source found nothing", so starting anyway would spend a full run's model
        # budget producing an evidence-free report — and, worse, one that reads as
        # research having looked.
        withheld = _REQUIRED_WEB_TOOLS & await self._disabled_tools()
        if withheld:
            raise ResearchUnavailableError(
                f"Deep research needs {', '.join(sorted(withheld))}, which "
                f"{'is' if len(withheld) == 1 else 'are'} switched off or offline."
            )

        try:
            main = await self._registry.resolve_detailed("main", owner_id=owner_id)
            background = await self._registry.resolve_background(owner_id=owner_id)
        except Exception as exc:
            raise ResearchUnavailableError(f"No usable model is configured: {exc}") from exc

        # The plan the operator would have refined interactively. One step, because
        # nobody is there to answer a clarifying question mid-turn — `context` is the
        # agent's substitute for that exchange.
        plan = await produce_plan(
            background.model, background.reasoning_off, question=question, context=context
        )

        row = ResearchRun(
            owner_id=owner_id,
            question_enc=self._vault.encrypt_str(question),
            status=ResearchStatus.DRAFT.value,
            plan_enc=research_store.encode_plan(self._vault, plan),
        )

        def save(session) -> ResearchRun:
            session.add(row)
            session.flush()
            session.refresh(row)
            return row

        saved = await in_session(self._engine, save)

        deps = ResearchDeps(
            owner_id=owner_id,
            main_model=main.model,
            utility_model=background.model,
            # The platform-wide parallel-tool default, handed to every pipeline agent at
            # the one seam that feeds them. Inert today — they are structured-output
            # calls with no toolset, and the rounds search in code — but wiring it here
            # means one that later grows a toolset isn't the one that missed out.
            main_settings=llm.with_parallel_tools(),
            utility_settings=llm.with_parallel_tools(background.reasoning_off),
            search=self._search,
            fetcher=self._fetcher,
            max_rounds=self._settings.research_max_rounds,
            time_limit_s=self._settings.research_time_limit_s,
            round_floor=self._settings.research_round_floor,
            max_concurrency=self._settings.research_max_concurrency,
            empty_rounds_abort=self._settings.research_empty_rounds_abort,
        )
        outcome = RunOutcome()

        async def orchestrate(run: Run) -> None:
            deps.cancel_requested = lambda: run.cancel_requested
            try:
                async with run.keepalive():
                    outcome.result = await run_research(plan, question, deps, run.emit)
            except Exception as exc:  # noqa: BLE001 — recorded, then re-raised
                outcome.error = str(exc)
                raise

        # Minted here so the row records it before the run can reach terminal — the
        # terminal hooks resolve their row by run id, and a fast failure would otherwise
        # find no row and drop its notification.
        run_id = new_id()
        started_at = utcnow()
        await research_store.mark_running(
            self._engine, saved.id, run_id=run_id, started_at=started_at
        )

        waiter: asyncio.Future[Run] = asyncio.get_running_loop().create_future()
        self._run_waiters[run_id] = waiter
        finalize_task = asyncio.create_task(
            research_store.finalize(self._engine, self._vault, saved.id, waiter, outcome)
        )
        self._terminal_tasks.add(finalize_task)
        finalize_task.add_done_callback(self._terminal_tasks.discard)

        try:
            self._runs.submit(
                kind="research",
                owner_id=owner_id,
                orchestrator=orchestrate,
                run_id=run_id,
                wall_clock_timeout_s=self._settings.research_time_limit_s
                + _WALL_CLOCK_BUFFER_S,
            )
        except Exception as exc:
            # Everything above was staged for a run that will now never exist. Unwind so
            # the row doesn't sit at `running` pointing at a run id nothing answers to.
            self._run_waiters.pop(run_id, None)
            finalize_task.cancel()
            await research_store.revert_launch(self._engine, saved.id, run_id=run_id)
            raise ResearchUnavailableError(f"Could not start the run: {exc}") from exc

        return LaunchedResearch(research_id=saved.id, run_id=run_id, question=question)

    async def snapshot(self, owner_id: str, research_id: str) -> ResearchSnapshot:
        row = await research_store.get_owned(self._engine, owner_id, research_id)
        if row is None:
            raise ResearchUnavailableError(f"No research entry {research_id!r}.")
        stats = row.stats or {}
        return ResearchSnapshot(
            research_id=row.id,
            question=self._vault.decrypt_str(row.question_enc),
            status=row.status,
            report=self._vault.decrypt_str(row.report_enc) if row.report_enc else None,
            sources=int(stats.get("sources", 0) or 0),
            findings=int(stats.get("findings", 0) or 0),
        )
