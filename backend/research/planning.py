"""The pre-run exchange: is this question researchable as asked, and what's the plan?

Two model calls that happen *before* any Run exists (`DR-1.6`). The utility model judges
whether a question is specific enough to research directly or worth a few clarifying
questions first; the main model turns the question plus whatever context the exchange has
gathered into a :class:`~research.state.ResearchPlan`.

These lived in the research router, which meant a route file owned two sets of model
instructions and drove two agents. They are research domain logic — nothing here knows
about HTTP, the database, or the operator's session — so they belong beside the pipeline
they feed. The router keeps what is genuinely its own: resolving which model plays each
role, and mapping a misconfigured registry to a status.
"""

from __future__ import annotations

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings

from .state import ResearchPlan

# `DR-1.6`: "up to a few clarifying questions" — capped so the planner can't turn the
# intake into an interrogation.
MAX_CLARIFYING_QUESTIONS = 3


class ClarifyVerdict(BaseModel):
    needs_clarification: bool
    questions: list[str] = []


CLARIFY_INSTRUCTIONS = (
    "You judge whether a research question is specific enough to research directly, or "
    "underspecified enough that a few clarifying questions would meaningfully sharpen "
    "the research (missing scope, timeframe, region, budget, or the criteria that "
    "matter to the person asking). Ask at most three short, specific clarifying "
    "questions, and only when an answer would actually change what gets researched — "
    "never ask for the sake of asking. If the question, together with any context "
    "already given, is specific enough to research as-is, set "
    "needs_clarification=false and return no questions."
)


PLAN_INSTRUCTIONS = (
    "You are the research planner. Produce a research plan for the question below: a "
    "one-sentence objective, three to six concrete and non-overlapping angles "
    "(sub-questions) worth investigating, and optional notes on scope or approach. If a "
    "current plan and operator feedback are given in the context, revise that plan to "
    "address the feedback rather than starting over from nothing."
)


def _prompt(question: str, context: str) -> str:
    """The question, plus whatever the exchange has gathered so far."""
    return f"Question: {question}" + (f"\n\nContext gathered so far:\n{context}" if context else "")


async def judge_clarification(
    model: Model, settings: ModelSettings | None, *, question: str, context: str
) -> ClarifyVerdict:
    agent = Agent(model, output_type=ClarifyVerdict, instructions=CLARIFY_INSTRUCTIONS, retries=2)
    result = await agent.run(_prompt(question, context), model_settings=settings)
    return result.output


async def produce_plan(
    model: Model, settings: ModelSettings | None, *, question: str, context: str
) -> ResearchPlan:
    agent = Agent(model, output_type=ResearchPlan, instructions=PLAN_INSTRUCTIONS, retries=2)
    result = await agent.run(_prompt(question, context), model_settings=settings)
    return result.output


def build_context(
    *,
    prior_questions: list[str],
    answers: list[str] | None,
    prior_plan: ResearchPlan | None,
    feedback: str | None,
) -> str:
    """Fold the pre-run exchange so far into one prompt block for the next judge/planner
    call — the questions already asked paired with their answers, the current plan (if
    any), and free-text feedback, whichever of these apply."""
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
