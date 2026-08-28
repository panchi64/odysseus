"""The research pipeline core — a deterministic rounds loop with a dynamic per-round
fan-out, driving the Pydantic AI agent calls in ``agents.py`` and emitting progress on
the Run's own (frozen) event protocol.

Library code only: no routes, no model resolution, no Run/app wiring — a plan and a
question go in, a :class:`~research.state.ResearchResult` comes out. See
``CLAUDE.md`` for the exact event frames this emits (the wiring batch builds its
``Orchestrator`` closure around :func:`run_research`, passing ``run.emit`` as
``emit`` and ``lambda: run.cancel_requested`` as the cancel check) and for a worked
example of the frame sequence.
"""

from __future__ import annotations

import asyncio
import logging
import time

from core.concurrency import gather_bounded
from core.exceptions import DegradedCapabilityError, SSRFError, WebFetchError
from runs import CitationAdded, LimitNotice, StepCompleted, StepStarted, ToolProgress
from services.search import SearchResult
from services.webfetch import FetchedPage

from . import agents
from .dedupe import DedupeSets, canonicalize_url, normalize_query
from .state import (
    EventEmitter,
    EvidenceClaim,
    EvidenceLedger,
    ResearchDeps,
    ResearchPlan,
    ResearchResult,
    SearchUnavailableError,
)

logger = logging.getLogger(__name__)

# How many of a query's top search hits are worth fetching — bounds a round's total
# read volume alongside the concurrency cap (DR-3.4).
_SOURCES_PER_QUERY = 3


async def run_research(
    plan: ResearchPlan,
    question: str,
    deps: ResearchDeps,
    emit: EventEmitter,
) -> ResearchResult:
    """Drive one research run from a frozen plan to a finished report.

    Rounds loop: an analyst (main model) turns the gaps still open into queries; a
    dynamic fan-out of workers searches and reads them into the evidence ledger
    (deduped run-wide, pre-network — DR-1.4); the analyst refines the evolving answer
    and gap list from the ledger; a judge (utility model, once ``deps.round_floor``
    rounds have run) decides whether the answer is comprehensive enough to stop
    (DR-3.2). Bounded by ``deps.max_rounds`` rounds or ``deps.time_limit_s`` wall-
    clock, whichever comes first (DR-3.1) — the Run's own wall-clock timeout is the
    backstop, not enforced here. Two consecutive rounds with zero usable search
    results raise :class:`SearchUnavailableError` (DR-4.1). A worker's failure loses
    only its own query/source, never the round (DR-4.2). The writer (main model) then
    produces the report strictly from the ledger (DR-1.3/2.1/2.2/2.3).
    """
    started = time.monotonic()
    step = 0
    gaps = list(plan.angles) or [plan.objective]
    ledger = EvidenceLedger()
    dedupe = DedupeSets()
    empty_rounds = 0
    round_num = 0

    while round_num < deps.max_rounds and (time.monotonic() - started) < deps.time_limit_s:
        _check_cancel(deps)
        round_num += 1

        step += 1
        emit(StepStarted(index=step, title="planning"))
        queries = await agents.select_queries(deps, question=question, plan=plan, gaps=gaps)
        emit(StepCompleted(index=step))

        fresh_queries = _select_fresh_queries(dedupe, queries, deps.max_concurrency)
        if not fresh_queries:
            break  # every open gap already covered or exhausted — converge to the writer

        step += 1
        emit(StepStarted(index=step, title="searching"))
        hit_batches = await gather_bounded(
            [_search_one(deps, q) for q in fresh_queries], deps.max_concurrency
        )
        emit(StepCompleted(index=step))

        total_hits = sum(len(hits) for hits in hit_batches)
        if total_hits == 0:
            empty_rounds += 1
            if empty_rounds >= deps.empty_rounds_abort:
                message = (
                    "Web search returned no usable results across "
                    f"{deps.empty_rounds_abort} consecutive rounds — search appears to "
                    "be unavailable. Stopping rather than return an empty or "
                    "fabricated report."
                )
                emit(LimitNotice(limit="search", message=message))
                raise SearchUnavailableError(message)
        else:
            empty_rounds = 0

        candidates: list[SearchResult] = []
        for hits in hit_batches:
            candidates.extend(hits[:_SOURCES_PER_QUERY])
        fresh_hits = _select_fresh_hits(dedupe, candidates, deps.max_concurrency)

        _check_cancel(deps)  # between this round's search and read batches
        step += 1
        emit(StepStarted(index=step, title="reading"))
        if fresh_hits:
            outcomes = await gather_bounded(
                [_read_one(deps, question, hit) for hit in fresh_hits], deps.max_concurrency
            )
            for outcome in outcomes:
                if outcome is None:
                    continue  # that worker's source is lost, not the round (DR-4.2)
                page, extracted = outcome
                if not extracted:
                    continue  # fetched but nothing relevant — not a "used" source
                if ledger.add_source(page.url, page.title):
                    emit(CitationAdded(url=page.url, title=page.title))
                ledger.add_claims(extracted)
        emit(StepCompleted(index=step))

        emit(
            ToolProgress(
                tool_call_id=f"research-round-{round_num}",
                partial=f"{ledger.source_count} sources, {ledger.claim_count} findings",
            )
        )

        step += 1
        emit(StepStarted(index=step, title="analyzing"))
        update = await agents.refine_answer(deps, question=question, plan=plan, ledger=ledger)
        gaps = update.gaps
        stop = False
        if round_num >= deps.round_floor:
            verdict = await agents.judge_comprehensive(
                deps, question=question, answer=update.answer, gaps=gaps
            )
            stop = verdict.comprehensive
        emit(StepCompleted(index=step))

        if stop or not gaps:
            break

    _check_cancel(deps)
    step += 1
    emit(StepStarted(index=step, title="writing"))
    report = await agents.write_report(deps, question=question, plan=plan, ledger=ledger)
    emit(StepCompleted(index=step))

    return ResearchResult(
        report=report,
        rounds=round_num,
        sources=ledger.source_count,
        queries=len(dedupe.seen_queries),
        duration_s=time.monotonic() - started,
        model=deps.main_model.model_name,
    )


def _check_cancel(deps: ResearchDeps) -> None:
    """Cooperative cancel check at a step boundary — mirrors the engine's own
    redundant check (``agent/engine.py``'s ``report_progress``): the registry's hard
    task-cancel almost always lands first; this only guards the rare case something
    upstream swallows that ``CancelledError`` too broadly."""
    if deps.cancel_requested():
        raise asyncio.CancelledError()


def _select_fresh_queries(
    dedupe: DedupeSets, queries: list[str], cap: int
) -> list[str]:
    """Cap first, mark second: pick up to ``cap`` not-yet-seen queries (folding out
    duplicates within this same batch too), then mark only those *selected* queries as
    seen in ``dedupe``. A query dropped only for being over the cap is never marked —
    it was never actually searched, so it stays eligible for a later round to
    re-propose, instead of being permanently blacklisted for work that never
    happened."""
    selected: list[str] = []
    pending: set[str] = set()
    for query in queries:
        key = normalize_query(query)
        if not key or key in pending or not dedupe.peek_query(query):
            continue
        pending.add(key)
        selected.append(query)
        if len(selected) >= cap:
            break
    for query in selected:
        dedupe.try_query(query)
    return selected


def _select_fresh_hits(
    dedupe: DedupeSets, candidates: list[SearchResult], cap: int
) -> list[SearchResult]:
    """Same cap-first-mark-second discipline as :func:`_select_fresh_queries`, keyed
    by canonical URL — an over-cap hit is never marked seen, so it remains fetchable in
    a later round instead of being silently blacklisted."""
    selected: list[SearchResult] = []
    pending: set[str] = set()
    for hit in candidates:
        key = canonicalize_url(hit.url)
        if not key or key in pending or not dedupe.peek_url(hit.url):
            continue
        pending.add(key)
        selected.append(hit)
        if len(selected) >= cap:
            break
    for hit in selected:
        dedupe.try_url(hit.url)
    return selected


async def _search_one(deps: ResearchDeps, query: str) -> list[SearchResult]:
    """One query's search leg. Isolates a failure to this query alone (DR-4.2): a
    degraded/unreachable provider or an unexpected error yields no hits rather than
    aborting the round."""
    if deps.search is None:
        return []
    try:
        results = await deps.search.search(deps.owner_id, query)
    except DegradedCapabilityError:
        return []
    except Exception:  # noqa: BLE001 — one worker's failure must not lose the round
        logger.warning("research search worker failed for query %r", query, exc_info=True)
        return []
    return list(results.results)


async def _read_one(
    deps: ResearchDeps, question: str, hit: SearchResult
) -> tuple[FetchedPage, list[EvidenceClaim]] | None:
    """One source's fetch + typed-evidence-extraction leg. ``None`` on any failure
    (DR-4.2): that source is lost, not the round."""
    if deps.fetcher is None:
        return None
    try:
        page = await deps.fetcher.fetch(deps.owner_id, hit.url, goal=question)
    except (SSRFError, WebFetchError):
        return None
    except Exception:  # noqa: BLE001 — one worker's failure must not lose the round
        logger.warning("research fetch worker failed for %r", hit.url, exc_info=True)
        return None
    try:
        claims = await agents.extract_evidence(deps, question=question, page=page)
    except Exception:  # noqa: BLE001 — an extraction failure still keeps the citation
        logger.warning("research extraction failed for %r", hit.url, exc_info=True)
        claims = []
    return page, claims
