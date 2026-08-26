"""Deep research — the durable research-entity record.

A :class:`ResearchRun` is one research entry: the operator's question, the pre-run
clarify/plan exchange (`DR-1.6`), and — once started — the Run it's driven by and the
finished report + stats (`DR-2.5`/`DR-7.1`). At-rest posture mirrors notifications/tasks:
the operator's own content (question, clarifying questions, plan, report) is encrypted;
``stats`` is deliberately **counts and durations only, never content**, so it stays in
the clear like any other structural metadata; ``status``/links/timestamps are likewise
unsealed so the library can list/order/filter without decrypting.

``run_id`` links to the Run substrate's own record for the duration of an execution (the
frontend rides the existing ``/runs/{id}/events`` stream for live progress and the
existing ``POST /runs/{id}/cancel`` for cancellation — this row never re-implements
either). ``conversation_id`` is set once "continue in chat" seeds a follow-up thread
with the finished report (`DR-1.5`/`DR-7.3`); its presence is what makes that action
idempotent — a second call finds it already set and returns the same id rather than
seeding twice.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from models._fields import new_id, utcnow


class ResearchStatus(StrEnum):
    """The REST contract's ``status`` vocabulary verbatim — a plain str column, like
    the other small in-code enumerations in this package."""

    DRAFT = "draft"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"


class ResearchRun(SQLModel, table=True):
    __tablename__ = "research"

    id: str = Field(default_factory=new_id, primary_key=True)
    owner_id: str = Field(index=True)
    # The project this belongs to, or null for **unfiled** — visible in every scope,
    # not orphaned. See models/project.py for the one scope rule.
    project_id: str | None = Field(default=None, index=True)

    # AEAD ciphertext — the operator's own content, sealed like a notification's
    # title/body or a task's title/prompt.
    question_enc: str
    status: str = Field(default=ResearchStatus.DRAFT.value, index=True)

    # Encrypted JSON. `clarifying_questions_enc` is a `list[str]` (absent once the
    # question was clear, or once a plan has been produced); `plan_enc` is the frozen
    # (or latest-refined-while-draft) `{objective, angles, notes?}` shape mirroring
    # `research.ResearchPlan`. Both are null until the pre-run clarify/plan exchange
    # produces them, and `plan_enc` is what `start` freezes into the actual run.
    clarifying_questions_enc: str | None = None
    plan_enc: str | None = None

    # The finished report (DR-1.3/2.1) once done — or, on an error/abort outcome
    # (DR-4.1), the clear operator-facing message in its place, so there is always
    # exactly one place a caller looks for "what happened", never an empty report.
    report_enc: str | None = None
    # Clear JSON — counts/durations only (durationS, rounds, sources, queries, model
    # in Python attribute form; the REST layer's CamelModel renders it camelCase), never
    # the operator's content. Null until the run finishes.
    stats: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))

    # The Run driving this execution, once started (`POST /research/{id}/start`) — the
    # frontend streams its progress via the existing `/runs/{id}/events` and cancels it
    # via the existing `/runs/{id}/cancel`; this row is never a second copy of that.
    run_id: str | None = Field(default=None, index=True)
    # Set once "continue in chat" seeds a follow-up conversation with the finished
    # report (DR-1.5/7.3) — its presence makes that action idempotent.
    conversation_id: str | None = Field(default=None, index=True)

    created_at: datetime = Field(default_factory=utcnow, index=True)
    started_at: datetime | None = None
    finished_at: datetime | None = None
