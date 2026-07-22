"""The deep-research surface — the pre-run clarify/plan exchange (REST, not a Run),
launching the frozen plan as a Run driven by ``research.run_research``, and the
completed-report library (`DR-1`/`DR-7`).

No dedicated service layer exists for this surface (mirrors `routes/tasks.py`): this
router reads/writes the ``research`` table directly via ``core.db.in_session`` and
drives the pipeline core (`research/`) straight from here. Out-shapes are camelCase,
like the app's other newer surfaces (documents/gallery/corpus/notifications/tasks).

**Pre-run vs run.** Intake/refine are plain request/response REST calls — a question
goes in, a clarify-or-plan judgement comes back, nothing is parked and no Run exists yet
(the design's "lightweight REST + utility/main-model calls on the Research surface").
Only ``start`` creates a Run: it submits ``research.run_research`` on the substrate
exactly like a chat turn submits the chat orchestrator, so progress rides the existing
``GET /runs/{id}/events`` and cancellation the existing ``POST /runs/{id}/cancel`` — this
surface never re-implements either.

**Terminal persistence.** ``start`` registers a waiter future for its Run's id (mirrors
the scheduler's agent-task executor in `app.py`) and spawns a background task that awaits
it, then writes the finished report/stats/status once the Run substrate resolves that
future via its ``on_terminal`` hook — safe against a mid-flight cancellation in a way
persisting *inside* the orchestrator's own (potentially cancelled) task wouldn't be.

**Continue in chat** (DR-1.5/7.3) reuses ``ConversationStore.record`` — the exact
mechanism an ordinary chat turn already persists through — to seed a fresh conversation
with a synthetic user/assistant exchange (the question, then the report) so the operator
can ask follow-ups without re-running the research. See ``research/CLAUDE.md`` for why
this was picked over a document+attachment seam. ``ResearchRun.conversation_id`` being
already set is what makes a repeat call idempotent.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from pydantic_ai import Agent, ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings
from sqlmodel import Session, select

from core.config import get_settings
from core.db import in_session
from core.exceptions import DegradedCapabilityError, NotFoundError
from core.untrusted import wrap_untrusted
from core.vault import Vault
from models._fields import utcnow
from models.research import ResearchRun, ResearchStatus
from research import ResearchDeps, ResearchPlan, ResearchResult, run_research
from routes import deps
from routes.camel import CamelModel
from routes.deps import OPERATOR_ID
from runs import Run, RunStatus

router = APIRouter(prefix="/research", tags=["research"])

# DR-1.6: "up to a few clarifying questions" — capped so the planner can't turn this
# into an interrogation.
_MAX_CLARIFYING_QUESTIONS = 3
# A research entry's title (its question) truncated for the seeded conversation's
# title and a notification's subject line — long enough to stay recognizable, short
# enough not to blow either surface's own display budget.
_TITLE_MAX_CHARS = 120

# The pipeline's own round loop enforces `research_time_limit_s` at round boundaries
# (DR-3.1), but that check can't cover the final, un-timed "writing" step that runs
# after the loop breaks — so the Run's own wall-clock bound (the outer backstop) is
# given a bit of slack above the operator-configured limit, rather than reusing the
# global chat default outright or matching it exactly and risking a hard cancel mid
# report. This is slack on the *backstop*, not the operator-facing limit itself
# (`research_deps.time_limit_s`, DR-6.1).
_WALL_CLOCK_BUFFER_S = 180.0

# How often the research Run's orchestrator touches activity while a single long
# Pydantic AI call (e.g. `write_report` on a slow local model) is in flight between
# the pipeline's own phase-boundary touches — comfortably inside the inactivity
# watchdog's default bound so a still-progressing call is never mistaken for a stall.
_HEARTBEAT_INTERVAL_S = 20.0


async def _heartbeat(run: Run, interval_s: float = _HEARTBEAT_INTERVAL_S) -> None:
    """Keep the run's activity clock alive for the duration of a single long
    in-flight call. The pipeline's own touches (``step.started``/``step.completed``,
    per-source ``citation.added``) only land at phase boundaries — a slow model
    generating a long report (or any other single-shot `agents.py` call) between two
    boundaries would otherwise look idle to the inactivity watchdog even while making
    real progress. Cancelled by the orchestrator once its awaited call returns."""
    try:
        while True:
            await asyncio.sleep(interval_s)
            run.touch()
    except asyncio.CancelledError:
        pass


# --- the two pre-run agent calls (utility judgement, main planning) ------------------


class ClarifyVerdict(BaseModel):
    needs_clarification: bool
    questions: list[str] = []


_CLARIFY_INSTRUCTIONS = (
    "You judge whether a research question is specific enough to research directly, or "
    "underspecified enough that a few clarifying questions would meaningfully sharpen "
    "the research (missing scope, timeframe, region, budget, or the criteria that "
    "matter to the person asking). Ask at most three short, specific clarifying "
    "questions, and only when an answer would actually change what gets researched — "
    "never ask for the sake of asking. If the question, together with any context "
    "already given, is specific enough to research as-is, set "
    "needs_clarification=false and return no questions."
)


async def _judge_clarification(
    model: Model, settings: ModelSettings | None, *, question: str, context: str
) -> ClarifyVerdict:
    agent = Agent(
        model, output_type=ClarifyVerdict, instructions=_CLARIFY_INSTRUCTIONS, retries=2
    )
    prompt = f"Question: {question}"
    if context:
        prompt += f"\n\nContext gathered so far:\n{context}"
    result = await agent.run(prompt, model_settings=settings)
    return result.output


_PLAN_INSTRUCTIONS = (
    "You are the research planner. Produce a research plan for the question below: a "
    "one-sentence objective, three to six concrete and non-overlapping angles "
    "(sub-questions) worth investigating, and optional notes on scope or approach. If a "
    "current plan and operator feedback are given in the context, revise that plan to "
    "address the feedback rather than starting over from nothing."
)


async def _produce_plan(
    model: Model, settings: ModelSettings | None, *, question: str, context: str
) -> ResearchPlan:
    agent = Agent(
        model, output_type=ResearchPlan, instructions=_PLAN_INSTRUCTIONS, retries=2
    )
    prompt = f"Question: {question}"
    if context:
        prompt += f"\n\nContext gathered so far:\n{context}"
    result = await agent.run(prompt, model_settings=settings)
    return result.output


def _build_context(
    *,
    prior_questions: list[str],
    answers: list[str] | None,
    prior_plan: ResearchPlan | None,
    feedback: str | None,
) -> str:
    """Fold the pre-run exchange so far into one prompt block for the next
    judge/planner call — the questions already asked paired with their answers, the
    current plan (if any), and free-text feedback, whichever of these apply."""
    parts: list[str] = []
    if prior_questions and answers:
        qa = "\n".join(
            f"Q: {q}\nA: {a}" for q, a in zip(prior_questions, answers, strict=False)
        )
        parts.append(f"Clarifying answers:\n{qa}")
    if prior_plan is not None:
        angles = ", ".join(prior_plan.angles) or "(none)"
        parts.append(
            "Current plan:\n"
            f"Objective: {prior_plan.objective}\nAngles: {angles}\n"
            f"Notes: {prior_plan.notes or '(none)'}"
        )
    if feedback:
        parts.append(f"Operator feedback:\n{feedback}")
    return "\n\n".join(parts)


@contextmanager
def _model_errors_to_http() -> Iterator[None]:
    """Map a misconfigured model registry to a clean HTTP status, exactly as
    ``chat.py`` does at run submission: a stale/deleted endpoint id → 404, an
    otherwise-degraded capability (no model bound, no native tool-calling, every
    endpoint in the chain disabled) → 503. Without this the research surface's
    model resolution surfaces registry misconfiguration as an unhandled 500."""
    try:
        yield
    except NotFoundError:
        raise HTTPException(status_code=404, detail="model endpoint not found") from None
    except DegradedCapabilityError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


async def _clarify_or_plan(
    request: Request, *, question: str, context: str, force_plan: bool
) -> tuple[list[str] | None, ResearchPlan | None]:
    """Either fresh clarifying questions or a plan — never both. ``force_plan`` skips
    the judge entirely (the skip/start-now affordance, DR-1.6: refine with no answers
    and no feedback forces a plan straight from whatever context exists)."""
    registry = deps.models(request)
    if not force_plan:
        with _model_errors_to_http():
            background = await registry.resolve_background(owner_id=OPERATOR_ID)
        verdict = await _judge_clarification(
            background.model, background.reasoning_off, question=question, context=context
        )
        if verdict.needs_clarification and verdict.questions:
            return verdict.questions[:_MAX_CLARIFYING_QUESTIONS], None
    with _model_errors_to_http():
        main = await registry.resolve_detailed("main", owner_id=OPERATOR_ID)
    # No conversation to inherit per-conversation settings from at this pre-run
    # stage either — deliberately `None`, not an oversight (see `start`'s
    # `research_deps.main_settings`).
    plan = await _produce_plan(main.model, None, question=question, context=context)
    return None, plan


# --- wire shapes ----------------------------------------------------------------------


class ResearchPlanOut(CamelModel):
    objective: str
    angles: list[str] = []
    notes: str | None = None


class ResearchStatsOut(CamelModel):
    duration_s: float
    rounds: int
    sources: int
    queries: int
    model: str


class ResearchOut(CamelModel):
    id: str
    question: str
    status: str
    clarifying_questions: list[str] | None = None
    plan: ResearchPlanOut | None = None
    report: str | None = None
    stats: ResearchStatsOut | None = None
    run_id: str | None = None
    conversation_id: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ResearchListOut(CamelModel):
    items: list[ResearchOut]


class IntakeIn(BaseModel):
    question: str


class RefineIn(BaseModel):
    answers: list[str] | None = None
    feedback: str | None = None


class ContinueOut(CamelModel):
    conversation_id: str


# --- encrypted-JSON encode/decode (plan, clarifying questions) ------------------------


def _encode_list(vault: Vault, values: list[str] | None) -> str | None:
    if not values:
        return None
    return vault.encrypt_str(json.dumps(values))


def _decode_list(vault: Vault, enc: str | None) -> list[str] | None:
    if enc is None:
        return None
    return json.loads(vault.decrypt_str(enc))


def _encode_plan(vault: Vault, plan: ResearchPlan | None) -> str | None:
    if plan is None:
        return None
    return vault.encrypt_str(plan.model_dump_json())


def _decode_plan(vault: Vault, enc: str | None) -> ResearchPlan | None:
    if enc is None:
        return None
    return ResearchPlan.model_validate_json(vault.decrypt_str(enc))


def _research_out(row: ResearchRun, vault: Vault, *, include_report: bool = True) -> ResearchOut:
    plan = _decode_plan(vault, row.plan_enc)
    report = vault.decrypt_str(row.report_enc) if include_report and row.report_enc else None
    return ResearchOut(
        id=row.id,
        question=vault.decrypt_str(row.question_enc),
        status=row.status,
        clarifying_questions=_decode_list(vault, row.clarifying_questions_enc),
        plan=ResearchPlanOut(objective=plan.objective, angles=plan.angles, notes=plan.notes)
        if plan is not None
        else None,
        report=report,
        stats=ResearchStatsOut(**row.stats) if row.stats else None,
        run_id=row.run_id,
        conversation_id=row.conversation_id,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )


# --- DB helpers -------------------------------------------------------------------


async def _get_owned(engine, owner_id: str, research_id: str) -> ResearchRun | None:
    def work(session: Session) -> ResearchRun | None:
        row = session.get(ResearchRun, research_id)
        if row is None or row.owner_id != owner_id:
            return None
        return row

    return await in_session(engine, work)


async def find_by_run(engine, run_id: str) -> ResearchRun | None:
    """The research row driven by ``run_id``, if any — used by ``app.py``'s run-terminal
    notifier to link a research run's outcome back to its research entity without a
    second app.state mapping (a plain indexed lookup, off the hot path)."""

    def work(session: Session) -> ResearchRun | None:
        return session.exec(select(ResearchRun).where(ResearchRun.run_id == run_id)).first()

    return await in_session(engine, work)


async def _mark_running(engine, research_id: str, *, run_id: str, started_at: datetime) -> None:
    def work(session: Session) -> None:
        row = session.get(ResearchRun, research_id)
        if row is None:
            return
        # Guarded, not unconditional: a fast enough Run can already reach terminal —
        # and have `_finalize_research` persist that outcome — before this write's own
        # threadpool commit lands (the two are independent awaits with no ordering
        # guarantee between them). Only stamp run_id/started_at when no launch has
        # been recorded yet (never clobber an already-recorded run), and only promote
        # draft -> running; never regress an already-finalized status
        # (done/error/cancelled) back to "running".
        if row.run_id is None:
            row.run_id = run_id
            row.started_at = started_at
        if row.status == ResearchStatus.DRAFT.value:
            row.status = ResearchStatus.RUNNING.value
        session.add(row)

    await in_session(engine, work)


@dataclass
class _RunOutcome:
    """What the orchestrate closure learned before its Run reached terminal — read by
    the finalize task once the terminal-transition waiter resolves. Set on every path
    except a genuine cancellation (there, neither is set and the finalizer falls back to
    ``run.status``/``run.error`` alone)."""

    result: ResearchResult | None = None
    error: str | None = None


async def _finalize_research(
    engine, vault: Vault, research_id: str, waiter: asyncio.Future[Run], outcome: _RunOutcome
) -> None:
    """Await the Run's terminal transition, then persist the report/stats/status it
    settled at. Runs as its own background task (not inside the orchestrator's own,
    potentially-cancelled task) so persisting is never itself at risk of being
    interrupted by the same cancellation it's recording."""
    run = await waiter

    def work(session: Session) -> None:
        row = session.get(ResearchRun, research_id)
        if row is None:
            return
        row.finished_at = utcnow()
        if run.status is RunStatus.done and outcome.result is not None:
            row.status = ResearchStatus.DONE.value
            row.report_enc = vault.encrypt_str(outcome.result.report)
            row.stats = {
                "duration_s": outcome.result.duration_s,
                "rounds": outcome.result.rounds,
                "sources": outcome.result.sources,
                "queries": outcome.result.queries,
                "model": outcome.result.model,
            }
        elif run.status is RunStatus.cancelled:
            row.status = ResearchStatus.CANCELLED.value
        else:
            # error (SearchUnavailableError included, DR-4.1) or blocked — the Run
            # substrate's wall-clock/inactivity bounds stop a run via `run.block(detail)`,
            # which records the operator-legible reason on `run.detail`, not `run.error` —
            # so the report field carries the clear message either way, never left empty.
            message = (
                outcome.error
                or run.error
                or run.detail
                or "research failed for an unknown reason"
            )
            row.status = ResearchStatus.ERROR.value
            row.report_enc = vault.encrypt_str(message)
        session.add(row)

    await in_session(engine, work)


# --- routes -------------------------------------------------------------------------


@router.get("", response_model=ResearchListOut)
async def list_research(request: Request) -> ResearchListOut:
    engine = deps.db_engine(request)
    vault = deps.vault(request)

    def work(session: Session) -> list[ResearchRun]:
        return list(
            session.exec(
                select(ResearchRun)
                .where(ResearchRun.owner_id == OPERATOR_ID)
                .order_by(ResearchRun.created_at.desc())
            ).all()
        )

    rows = await in_session(engine, work)
    return ResearchListOut(
        items=[_research_out(row, vault, include_report=False) for row in rows]
    )


@router.post("/intake", status_code=201, response_model=ResearchOut)
async def intake_research(body: IntakeIn, request: Request) -> ResearchOut:
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="question must not be empty")

    clarifying_questions, plan = await _clarify_or_plan(
        request, question=question, context="", force_plan=False
    )

    engine = deps.db_engine(request)
    vault = deps.vault(request)
    row = ResearchRun(
        owner_id=OPERATOR_ID,
        question_enc=vault.encrypt_str(question),
        status=ResearchStatus.DRAFT.value,
        clarifying_questions_enc=_encode_list(vault, clarifying_questions),
        plan_enc=_encode_plan(vault, plan),
    )

    def work(session: Session) -> ResearchRun:
        session.add(row)
        session.flush()
        session.refresh(row)
        return row

    saved = await in_session(engine, work)
    return _research_out(saved, vault)


@router.post("/{research_id}/refine", response_model=ResearchOut)
async def refine_research(research_id: str, body: RefineIn, request: Request) -> ResearchOut:
    engine = deps.db_engine(request)
    vault = deps.vault(request)
    row = await _get_owned(engine, OPERATOR_ID, research_id)
    if row is None:
        raise HTTPException(status_code=404, detail="research not found")
    if row.status != ResearchStatus.DRAFT.value:
        raise HTTPException(status_code=409, detail="research is no longer a draft")

    question = vault.decrypt_str(row.question_enc)
    prior_questions = _decode_list(vault, row.clarifying_questions_enc) or []
    prior_plan = _decode_plan(vault, row.plan_enc)
    context = _build_context(
        prior_questions=prior_questions,
        answers=body.answers,
        prior_plan=prior_plan,
        feedback=body.feedback,
    )
    # An empty call (no answers, no feedback) is the skip/start-now affordance
    # (DR-1.6): force straight to a plan from whatever context already exists,
    # rather than asking the clarify judge to weigh in again.
    force_plan = not body.answers and not body.feedback
    clarifying_questions, plan = await _clarify_or_plan(
        request, question=question, context=context, force_plan=force_plan
    )

    def work(session: Session) -> ResearchRun | None:
        current = session.get(ResearchRun, research_id)
        if current is None:
            return None
        current.clarifying_questions_enc = _encode_list(vault, clarifying_questions)
        current.plan_enc = _encode_plan(vault, plan)
        session.add(current)
        session.flush()
        session.refresh(current)
        return current

    saved = await in_session(engine, work)
    if saved is None:
        raise HTTPException(status_code=404, detail="research not found")
    return _research_out(saved, vault)


# Research ids an in-flight `start` currently holds — the same synchronous
# check-and-claim discipline `RunRegistry.claim` gives the conversation routes
# (`deps.claim_conversation`), scoped to this surface: `start` reads the draft
# status, resolves models, and submits the Run across several real ``await``s, so
# two near-simultaneous starts could otherwise both observe "still a draft" and
# both submit a real Run — one pipeline's entire execution (model + search + fetch
# spend) silently discarded, the row reflecting whichever write landed last. The
# claim is taken before the route's first ``await`` and released in a ``finally``
# covering every exit path, after which the DB status itself refuses a re-start.
_start_claims: set[str] = set()


@router.post("/{research_id}/start", response_model=ResearchOut)
async def start_research(research_id: str, request: Request) -> ResearchOut:
    # Synchronous check-and-claim before the first ``await``: under single-threaded
    # asyncio only the first of two near-simultaneous starts can take the claim, so
    # the loser 409s here — before it can resolve models or submit a duplicate Run.
    if research_id in _start_claims:
        raise HTTPException(status_code=409, detail="research is already being started")
    _start_claims.add(research_id)
    try:
        return await _start_claimed(research_id, request)
    finally:
        _start_claims.discard(research_id)


async def _start_claimed(research_id: str, request: Request) -> ResearchOut:
    """The body of ``start`` — runs with the research id's start claim held."""
    engine = deps.db_engine(request)
    vault = deps.vault(request)
    row = await _get_owned(engine, OPERATOR_ID, research_id)
    if row is None:
        raise HTTPException(status_code=404, detail="research not found")
    if row.status != ResearchStatus.DRAFT.value:
        raise HTTPException(status_code=409, detail="research is not in draft")
    plan = _decode_plan(vault, row.plan_enc)
    if plan is None:
        raise HTTPException(
            status_code=422,
            detail="no plan to start from — refine (or refine with no feedback to skip"
            " straight to a plan) before starting",
        )
    question = vault.decrypt_str(row.question_enc)

    settings = get_settings()
    registry = deps.models(request)
    with _model_errors_to_http():
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
    outcome = _RunOutcome()

    async def orchestrate(run: Run) -> None:
        research_deps.cancel_requested = lambda: run.cancel_requested
        heartbeat = asyncio.create_task(_heartbeat(run))
        try:
            outcome.result = await run_research(plan, question, research_deps, run.emit)
        except Exception as exc:  # noqa: BLE001 — recorded, then re-raised for the registry
            outcome.error = str(exc)
            raise
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat

    run = deps.registry(request).submit(
        kind="research",
        owner_id=OPERATOR_ID,
        orchestrator=orchestrate,
        # The operator-configurable research time limit is the outer bound this
        # Run's own wall-clock backstop must honor — not the global chat default
        # (`Settings.run_wall_clock_timeout_s`), which would silently override it.
        wall_clock_timeout_s=settings.research_time_limit_s + _WALL_CLOCK_BUFFER_S,
    )

    # Registered before the very first `await` below — `submit` only schedules the
    # run's task, so there is no window for it to reach terminal before this waiter
    # exists (mirrors the scheduler's agent-task executor in `app.py`).
    waiter: asyncio.Future[Run] = asyncio.get_running_loop().create_future()
    deps.research_run_waiters(request)[run.id] = waiter
    finalize_task = asyncio.create_task(
        _finalize_research(engine, vault, research_id, waiter, outcome)
    )
    terminal_tasks = deps.run_terminal_tasks(request)
    terminal_tasks.add(finalize_task)
    finalize_task.add_done_callback(terminal_tasks.discard)

    # A fast enough Run — realistically only a test fake, since a real pipeline call
    # always spends real wall-clock time on network/model round trips — can already
    # reach terminal (and have `_finalize_research` persist that outcome) before this
    # write's own commit lands, let alone before a *second*, separate re-read of the
    # row would run. Rather than re-querying (and risking this response racing ahead
    # to report a later state), mirror the exact values this write just persisted onto
    # the row already in hand: this response always reports "just started", which is
    # what actually happened here, regardless of how far the background run has since
    # progressed — its own current state is always available via `GET /research/{id}`
    # or the run's own event stream.
    started_at = utcnow()
    await _mark_running(engine, research_id, run_id=run.id, started_at=started_at)
    row.run_id = run.id
    row.started_at = started_at
    row.status = ResearchStatus.RUNNING.value
    return _research_out(row, vault)


@router.get("/{research_id}", response_model=ResearchOut)
async def get_research(research_id: str, request: Request) -> ResearchOut:
    engine = deps.db_engine(request)
    vault = deps.vault(request)
    row = await _get_owned(engine, OPERATOR_ID, research_id)
    if row is None:
        raise HTTPException(status_code=404, detail="research not found")
    return _research_out(row, vault)


@router.delete("/{research_id}", status_code=204)
async def delete_research(research_id: str, request: Request) -> None:
    engine = deps.db_engine(request)
    row = await _get_owned(engine, OPERATOR_ID, research_id)
    if row is None:
        raise HTTPException(status_code=404, detail="research not found")
    if row.status == ResearchStatus.RUNNING.value:
        raise HTTPException(status_code=409, detail="cannot delete a running research")

    def work(session: Session) -> None:
        current = session.get(ResearchRun, research_id)
        if current is not None:
            session.delete(current)

    await in_session(engine, work)


async def _set_conversation_id_if_absent(engine, research_id: str, conversation_id: str) -> bool:
    def work(session: Session) -> bool:
        row = session.get(ResearchRun, research_id)
        if row is None or row.conversation_id is not None:
            return False
        row.conversation_id = conversation_id
        session.add(row)
        return True

    return await in_session(engine, work)


@router.post("/{research_id}/continue", response_model=ContinueOut)
async def continue_research(research_id: str, request: Request) -> ContinueOut:
    engine = deps.db_engine(request)
    vault = deps.vault(request)
    row = await _get_owned(engine, OPERATOR_ID, research_id)
    if row is None:
        raise HTTPException(status_code=404, detail="research not found")
    if row.conversation_id is not None:
        return ContinueOut(conversation_id=row.conversation_id)  # idempotent
    if row.status != ResearchStatus.DONE.value or row.report_enc is None:
        raise HTTPException(
            status_code=409, detail="research has no finished report to continue from"
        )

    question = vault.decrypt_str(row.question_enc)
    report = vault.decrypt_str(row.report_enc)
    store = deps.store(request)
    conversation_id = await store.create_conversation(
        OPERATOR_ID, title=question[:_TITLE_MAX_CHARS]
    )
    # Seed the new thread with the question and the finished report as an ordinary
    # request/response exchange — the exact mechanism a live chat turn already
    # persists through (`ConversationStore.record`), so the report becomes available
    # context for a follow-up without re-running the research (DR-1.5/7.3). The report
    # is seeded as the assistant's own prior turn — retained, poisonable history for
    # every future turn in this conversation — but it was built from web content that
    # only survived a soft-instruction extraction step (see
    # `EvidenceLedger.render_context`), so it must still carry the same untrusted
    # marking every other web-sourced text carries through history, or a successful
    # prompt injection in a source page becomes an assistant-authored instruction the
    # model later treats as its own trusted past statement.
    store.record(
        conversation_id,
        [
            ModelRequest(parts=[UserPromptPart(content=f"Research: {question}")]),
            ModelResponse(parts=[TextPart(content=wrap_untrusted(report, source="research"))]),
        ],
    )
    if not await _set_conversation_id_if_absent(engine, research_id, conversation_id):
        # Lost a race with a concurrent `continue` call — its winning id is the one
        # every caller must agree on; the conversation this call just seeded is simply
        # left as harmless orphaned history rather than reconciled away.
        winner = await _get_owned(engine, OPERATOR_ID, research_id)
        if winner is not None and winner.conversation_id is not None:
            return ContinueOut(conversation_id=winner.conversation_id)
    return ContinueOut(conversation_id=conversation_id)
