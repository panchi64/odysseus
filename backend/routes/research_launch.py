"""Turning a frozen plan into a running Run.

Everything between "the operator pressed start" and "a Run is executing": the pre-flight
refusals, assembling :class:`~research.state.ResearchDeps` from the registry and settings,
minting the run id so the row records it before the run can reach terminal, wiring the
terminal waiter, and unwinding all of it if the submit fails.

Split out of the router because it is orchestration, not routing — the route above it
decides who may start what and how the answer is shaped, and this decides what starting
means. It deliberately returns the ``ResearchRun`` row rather than a wire shape, so the
projection stays the router's business and the two don't have to import each other.
"""

from __future__ import annotations

import asyncio

from fastapi import HTTPException, Request

from core.config import get_settings
from models._fields import new_id, utcnow
from models.research import ResearchRun, ResearchStatus
from research import ResearchDeps, run_research
from routes import deps, research_store
from routes.deps import OPERATOR_ID
from routes.research_store import RunOutcome
from runs import Run

# The namespaced tool names deep research *is* — every round is outbound search plus
# browser fetch, and the pipeline has no other way to gather evidence. Named here rather
# than imported from `services/offline` because this is a statement about what the
# pipeline needs, not about what offline mode happens to suspend; the two sets coincide
# today and each should be free to move.
_REQUIRED_WEB_TOOLS = frozenset({"web_search", "web_fetch"})

# The pipeline's own round loop enforces `research_time_limit_s` at round boundaries
# (DR-3.1), but that check can't cover the final, un-timed "writing" step that runs
# after the loop breaks — so the Run's own wall-clock bound (the outer backstop) is
# given a bit of slack above the operator-configured limit, rather than reusing the
# global chat default outright or matching it exactly and risking a hard cancel mid
# report. This is slack on the *backstop*, not the operator-facing limit itself
# (`research_deps.time_limit_s`, DR-6.1).
_WALL_CLOCK_BUFFER_S = 180.0

# Research ids an in-flight `start` currently holds — the same synchronous
# check-and-claim discipline `RunRegistry.claim` gives the conversation routes
# (`deps.claim_conversation`), scoped to this surface: starting reads the draft
# status, resolves models, and submits the Run across several real ``await``s, so
# two near-simultaneous starts could otherwise both observe "still a draft" and
# both submit a real Run — one pipeline's entire execution (model + search + fetch
# spend) silently discarded, the row reflecting whichever write landed last. The
# claim is taken before the first ``await`` and released in a ``finally`` covering
# every exit path, after which the DB status itself refuses a re-start.
_start_claims: set[str] = set()


async def start(research_id: str, request: Request, *, on_registry_error) -> ResearchRun:
    """Launch ``research_id``, returning the row as it now stands.

    ``on_registry_error`` is the router's context manager for a misconfigured model
    registry — resolving models is this module's job, but how a missing endpoint reads to
    the operator is the surface's.
    """
    # Synchronous check-and-claim before the first ``await``: under single-threaded
    # asyncio only the first of two near-simultaneous starts can take the claim, so the
    # loser 409s here — before it can resolve models or submit a duplicate Run.
    if research_id in _start_claims:
        raise HTTPException(status_code=409, detail="research is already being started")
    _start_claims.add(research_id)
    try:
        return await _start_claimed(research_id, request, on_registry_error=on_registry_error)
    finally:
        _start_claims.discard(research_id)


async def _start_claimed(
    research_id: str, request: Request, *, on_registry_error
) -> ResearchRun:
    """The body of :func:`start` — runs with the research id's claim held."""
    engine = deps.db_engine(request)
    vault = deps.vault(request)
    row = await research_store.get_owned(engine, OPERATOR_ID, research_id)
    if row is None:
        raise HTTPException(status_code=404, detail="research not found")
    if row.status != ResearchStatus.DRAFT.value:
        raise HTTPException(status_code=409, detail="research is not in draft")
    plan = research_store.decode_plan(vault, row.plan_enc)
    if plan is None:
        raise HTTPException(
            status_code=422,
            detail="no plan to start from — refine (or refine with no feedback to skip"
            " straight to a plan) before starting",
        )
    question = vault.decrypt_str(row.question_enc)

    # Research is a run path like any other, so it honors the same effective disabled set
    # the chat turn, the approval-resume, and the scheduler's executor do (`AE-3.3`
    # unioned with offline mode's automatic web suspension) — resolved through the one
    # dependency that composes both sources, so this can't drift into applying one and
    # dropping the other. Refuse rather than degrade: `_search_one`/`_read_one` treat a
    # missing capability as "this source found nothing", so starting anyway would burn a
    # full Run's model budget to produce an evidence-free report — and, worse, would read
    # as research having *looked*. The message names the two switches that can cause it.
    withheld = _REQUIRED_WEB_TOOLS & await deps.disabled_tools(request)
    if withheld:
        raise HTTPException(
            status_code=409,
            detail=(
                f"deep research needs {', '.join(sorted(withheld))}, which "
                f"{'is' if len(withheld) == 1 else 'are'} currently unavailable — "
                "re-enable the web tools in settings, or leave offline mode, and start again"
            ),
        )

    settings = get_settings()
    registry = deps.models(request)
    with on_registry_error():
        main = await registry.resolve_detailed("main", owner_id=OPERATOR_ID)
        background = await registry.resolve_background(owner_id=OPERATOR_ID)
    research_deps = ResearchDeps(
        owner_id=OPERATOR_ID,
        main_model=main.model,
        utility_model=background.model,
        # No per-conversation settings to inherit — research has no conversation of
        # its own, unlike a chat turn's resolved `main`; deliberately `None`, not an
        # oversight.
        main_settings=None,
        utility_settings=background.reasoning_off,
        search=deps.search(request),
        fetcher=deps.fetcher(request),
        max_rounds=settings.research_max_rounds,
        time_limit_s=settings.research_time_limit_s,
        round_floor=settings.research_round_floor,
        max_concurrency=settings.research_max_concurrency,
        empty_rounds_abort=settings.research_empty_rounds_abort,
    )
    outcome = RunOutcome()

    async def orchestrate(run: Run) -> None:
        research_deps.cancel_requested = lambda: run.cancel_requested
        # The pipeline's own touches (`step.started`/`step.completed`, per-source
        # `citation.added`) only land at phase boundaries. A slow model generating a long
        # report between two of them looks idle to the watchdog while making real
        # progress, so the substrate's keepalive holds the clock open for it.
        try:
            async with run.keepalive():
                outcome.result = await run_research(plan, question, research_deps, run.emit)
        except Exception as exc:  # noqa: BLE001 — recorded, then re-raised for the registry
            outcome.error = str(exc)
            raise

    # The run id is minted here rather than by `submit`, so the row can record it
    # *before* the run exists to reach terminal. The terminal hooks resolve their
    # research row by run id (`find_by_run`); a run that settles instantly — a fast
    # failure like an immediately-raising pipeline, not just a test fake — would
    # otherwise find no row yet and drop its notification silently.
    run_id = new_id()
    started_at = utcnow()
    await research_store.mark_running(engine, research_id, run_id=run_id, started_at=started_at)

    # Both registered before submit, so there is no window in which the run could
    # reach terminal without a waiter to resolve (mirrors the scheduler's agent-task
    # executor in `app.py`).
    waiter: asyncio.Future[Run] = asyncio.get_running_loop().create_future()
    deps.research_run_waiters(request)[run_id] = waiter
    finalize_task = asyncio.create_task(
        research_store.finalize(engine, vault, research_id, waiter, outcome)
    )
    terminal_tasks = deps.run_terminal_tasks(request)
    terminal_tasks.add(finalize_task)
    finalize_task.add_done_callback(terminal_tasks.discard)

    try:
        deps.registry(request).submit(
            kind="research",
            owner_id=OPERATOR_ID,
            orchestrator=orchestrate,
            run_id=run_id,
            # The operator-configurable research time limit is the outer bound this
            # Run's own wall-clock backstop must honor — not the global chat default
            # (`Settings.run_wall_clock_timeout_s`), which would silently override it.
            wall_clock_timeout_s=settings.research_time_limit_s + _WALL_CLOCK_BUFFER_S,
        )
    except Exception:
        # Everything above was staged for a run that now will never exist. Without this
        # the row would sit at `running` forever, pointing at a run id nothing answers
        # to, while `finalize_task` awaited a future no terminal hook can resolve.
        # Unwind to `draft` so the operator can simply press start again.
        deps.research_run_waiters(request).pop(run_id, None)
        finalize_task.cancel()
        await research_store.revert_launch(engine, research_id, run_id=run_id)
        raise

    # A fast enough Run can already have reached terminal (and had `research_store.finalize`
    # persist that outcome) by the time we return. Rather than re-querying (and risking
    # this response racing ahead to report a later state), mirror the exact values the
    # write above persisted onto the row already in hand: the caller always reports
    # "just started", which is what actually happened here, regardless of how far the
    # background run has since progressed — its own current state is always available
    # via `GET /research/{id}` or the run's own event stream.
    row.run_id = run_id
    row.started_at = started_at
    row.status = ResearchStatus.RUNNING.value
    return row
