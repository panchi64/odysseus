"""The deep-research surface — the pre-run clarify/plan exchange (REST, not a Run),
launching the frozen plan as a Run driven by ``research.run_research``, and the
completed-report library (`DR-1`/`DR-7`).

No dedicated service layer exists for this surface (mirrors `routes/tasks.py`): the
router owns the ``research`` table and drives the pipeline core (`research/`) itself,
rather than through a class that would own no decisions. Out-shapes are camelCase, like
the app's other newer surfaces (documents/gallery/corpus/notifications/tasks).

That doesn't mean it all lives in one file. Three neighbours carry what is not routing:

- ``research.planning`` — the two pre-run model calls. They are research domain logic
  (a router should not own two sets of model instructions), and nothing in them knows
  about HTTP or the database.
- ``routes.research_store`` — the seal and the row reads/writes, including the terminal
  write. A router should not also be where the encryption of a stored plan is decided.
- ``routes.research_launch`` — everything between "the operator pressed start" and "a Run
  is executing". That is orchestration; this file decides who may start what and how the
  answer is shaped, and that one decides what starting means.

What stays here: the wire shapes, the endpoints, which model plays each pre-run role, and
how a misconfigured registry reads to the operator.

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

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from pydantic_ai import ModelRequest, ModelResponse, TextPart, UserPromptPart
from sqlmodel import Session, select

from core.db import in_session
from core.exceptions import NotFoundError
from core.untrusted import wrap_untrusted
from core.vault import Vault
from models.research import ResearchRun, ResearchStatus
from research import ResearchPlan
from research.planning import (
    MAX_CLARIFYING_QUESTIONS,
    ClarifyVerdict,
    build_context,
    judge_clarification,
    produce_plan,
)
from routes import deps, research_launch, research_store
from routes.camel import CamelModel
from routes.deps import OPERATOR_ID
from routes.research_store import find_by_run
from services.projects import project_clause

__all__ = ["ClarifyVerdict", "find_by_run", "router"]

router = APIRouter(prefix="/research", tags=["research"])

# A research entry's title (its question) truncated for the seeded conversation's
# title and a notification's subject line — long enough to stay recognizable, short
# enough not to blow either surface's own display budget.
_TITLE_MAX_CHARS = 120

# --- resolving who plans, and what a misconfigured registry answers -------------------


@contextmanager
def _model_errors_to_http() -> Iterator[None]:
    """Name the missing thing. The shared handler already answers a `NotFoundError` with
    404 — but the registry's message names an endpoint id the operator never typed, where
    "model endpoint not found" tells them what kind of thing is missing. A degraded
    capability needs no help here: `core.http_errors` maps it to 503 with its own words."""
    try:
        yield
    except NotFoundError:
        raise HTTPException(status_code=404, detail="model endpoint not found") from None


async def _clarify_or_plan(
    request: Request, *, question: str, context: str, force_plan: bool
) -> tuple[list[str] | None, ResearchPlan | None]:
    """Either fresh clarifying questions or a plan — never both. ``force_plan`` skips
    the judge entirely (the skip/start-now affordance, DR-1.6: refine with no answers
    and no feedback forces a plan straight from whatever context exists).

    The judgement and the planning themselves are `research.planning`; what belongs here
    is which model plays each role, which only the registry can answer."""
    registry = deps.models(request)
    if not force_plan:
        with _model_errors_to_http():
            background = await registry.resolve_background(owner_id=OPERATOR_ID)
        verdict = await judge_clarification(
            background.model, background.reasoning_off, question=question, context=context
        )
        if verdict.needs_clarification and verdict.questions:
            return verdict.questions[:MAX_CLARIFYING_QUESTIONS], None
    with _model_errors_to_http():
        main = await registry.resolve_detailed("main", owner_id=OPERATOR_ID)
    # No conversation to inherit per-conversation settings from at this pre-run
    # stage either — deliberately `None`, not an oversight (see `start`'s
    # `research_deps.main_settings`).
    plan = await produce_plan(main.model, None, question=question, context=context)
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


def _research_out(row: ResearchRun, vault: Vault, *, include_report: bool = True) -> ResearchOut:
    plan = research_store.decode_plan(vault, row.plan_enc)
    report = vault.decrypt_str(row.report_enc) if include_report and row.report_enc else None
    return ResearchOut(
        id=row.id,
        question=vault.decrypt_str(row.question_enc),
        status=row.status,
        clarifying_questions=research_store.decode_list(vault, row.clarifying_questions_enc),
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


# --- routes -------------------------------------------------------------------------


@router.get("", response_model=ResearchListOut)
async def list_research(request: Request) -> ResearchListOut:
    engine = deps.db_engine(request)
    vault = deps.vault(request)

    scope = project_clause(ResearchRun.project_id, await deps.project_scope(request))

    def work(session: Session) -> list[ResearchRun]:
        query = select(ResearchRun).where(ResearchRun.owner_id == OPERATOR_ID)
        if scope is not None:
            query = query.where(scope)
        return list(session.exec(query.order_by(ResearchRun.created_at.desc())).all())

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
        clarifying_questions_enc=research_store.encode_list(vault, clarifying_questions),
        plan_enc=research_store.encode_plan(vault, plan),
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
    row = await research_store.get_owned(engine, OPERATOR_ID, research_id)
    if row is None:
        raise HTTPException(status_code=404, detail="research not found")
    if row.status != ResearchStatus.DRAFT.value:
        raise HTTPException(status_code=409, detail="research is no longer a draft")

    question = vault.decrypt_str(row.question_enc)
    prior_questions = research_store.decode_list(vault, row.clarifying_questions_enc) or []
    prior_plan = research_store.decode_plan(vault, row.plan_enc)
    context = build_context(
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
        current.clarifying_questions_enc = research_store.encode_list(vault, clarifying_questions)
        current.plan_enc = research_store.encode_plan(vault, plan)
        session.add(current)
        session.flush()
        session.refresh(current)
        return current

    saved = await in_session(engine, work)
    if saved is None:
        raise HTTPException(status_code=404, detail="research not found")
    return _research_out(saved, vault)


@router.post("/{research_id}/start", response_model=ResearchOut)
async def start_research(research_id: str, request: Request) -> ResearchOut:
    """Launch the frozen plan as a Run. What starting *means* — the pre-flight refusals,
    the deps, the run wiring and its unwind — is `research_launch`; this decides how the
    answer is shaped and what a misconfigured registry reads as."""
    row = await research_launch.start(
        research_id, request, on_registry_error=_model_errors_to_http
    )
    return _research_out(row, deps.vault(request))


@router.get("/{research_id}", response_model=ResearchOut)
async def get_research(research_id: str, request: Request) -> ResearchOut:
    engine = deps.db_engine(request)
    vault = deps.vault(request)
    row = await research_store.get_owned(engine, OPERATOR_ID, research_id)
    if row is None:
        raise HTTPException(status_code=404, detail="research not found")
    return _research_out(row, vault)


@router.delete("/{research_id}", status_code=204)
async def delete_research(research_id: str, request: Request) -> None:
    engine = deps.db_engine(request)
    row = await research_store.get_owned(engine, OPERATOR_ID, research_id)
    if row is None:
        raise HTTPException(status_code=404, detail="research not found")
    if row.status == ResearchStatus.RUNNING.value:
        raise HTTPException(status_code=409, detail="cannot delete a running research")

    def work(session: Session) -> None:
        current = session.get(ResearchRun, research_id)
        if current is not None:
            session.delete(current)

    await in_session(engine, work)


@router.post("/{research_id}/continue", response_model=ContinueOut)
async def continue_research(research_id: str, request: Request) -> ContinueOut:
    engine = deps.db_engine(request)
    vault = deps.vault(request)
    row = await research_store.get_owned(engine, OPERATOR_ID, research_id)
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
    if not await research_store.set_conversation_id_if_absent(engine, research_id, conversation_id):
        # Lost a race with a concurrent `continue` call — its winning id is the one
        # every caller must agree on; the conversation this call just seeded is simply
        # left as harmless orphaned history rather than reconciled away.
        winner = await research_store.get_owned(engine, OPERATOR_ID, research_id)
        if winner is not None and winner.conversation_id is not None:
            return ContinueOut(conversation_id=winner.conversation_id)
    return ContinueOut(conversation_id=conversation_id)
