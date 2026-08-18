"""ManagedModelStore — the managed_models row persistence (sync-in-threadpool CRUD).

Split out of ``ServingService`` so the mechanical row store (one reason to change: the
table) is separate from the serve/download lifecycle. Every method runs its work through
``core.db.in_session`` on the threadpool, like the rest of the codebase's DB access.
"""

from __future__ import annotations

import logging

from pydantic import ValidationError
from sqlalchemy import Engine
from sqlmodel import Session, select

from core.db import in_session
from core.exceptions import NotFoundError
from models._fields import utcnow
from models.serving import ManagedModel

from .models import EngineKind, LaunchOptions, ManagedModelView, ServeState, Workload

# States that imply a live process or in-flight job — what a restart must clean up, since
# the supervisor's process table didn't survive the prior process.
ACTIVE_STATES = frozenset(
    {ServeState.running.value, ServeState.starting.value, ServeState.downloading.value}
)

logger = logging.getLogger(__name__)


def launch_options(row: ManagedModel) -> LaunchOptions:
    """The row's launch overrides. Degrade, don't crash: a blob this build can no longer
    parse (an option removed across versions, a hand-edited row) reads as "no overrides"
    so the model still serves on engine defaults instead of the status list erroring."""
    try:
        return LaunchOptions.model_validate(row.launch_options or {})
    except ValidationError:
        logger.warning("serving: unreadable launch_options on %s — using defaults", row.id)
        return LaunchOptions()


class ManagedModelStore:
    def __init__(self, db_engine: Engine) -> None:
        self._db = db_engine

    async def list_rows(self, owner_id: str) -> list[ManagedModel]:
        def work(session: Session) -> list[ManagedModel]:
            return list(
                session.exec(
                    select(ManagedModel)
                    .where(ManagedModel.owner_id == owner_id)
                    .order_by(ManagedModel.created_at)
                ).all()
            )

        return await in_session(self._db, work)

    async def active_rows(self) -> list[ManagedModel]:
        """Every owner's managed models still in a non-terminal state — what startup
        reconcile must clean-slate."""

        def work(session: Session) -> list[ManagedModel]:
            return list(
                session.exec(
                    select(ManagedModel).where(ManagedModel.state.in_(ACTIVE_STATES))  # type: ignore[attr-defined]
                ).all()
            )

        return await in_session(self._db, work)

    async def get(self, managed_id: str) -> ManagedModel | None:
        def work(session: Session) -> ManagedModel | None:
            return session.get(ManagedModel, managed_id)

        return await in_session(self._db, work)

    async def get_owned(self, owner_id: str, managed_id: str) -> ManagedModel:
        row = await self.get(managed_id)
        if row is None or row.owner_id != owner_id:
            raise NotFoundError(f"managed model {managed_id!r} not found")
        return row

    async def delete(self, managed_id: str) -> None:
        def work(session: Session) -> None:
            row = session.get(ManagedModel, managed_id)
            if row is not None:
                session.delete(row)

        await in_session(self._db, work)

    async def get_or_create(
        self,
        owner_id: str,
        engine: EngineKind,
        repo: str,
        workload: Workload,
        quant: str | None,
        options: LaunchOptions | None = None,
    ) -> ManagedModel:
        """One row per (owner, engine, repo) — re-downloading reuses it.

        ``options`` is only written when supplied, unlike ``workload``/``quant``: the
        download path carries no launch overrides, and letting it through as ``None``
        would wipe the ones the operator set on the last serve.
        """

        def work(session: Session) -> ManagedModel:
            existing = session.exec(
                select(ManagedModel).where(
                    ManagedModel.owner_id == owner_id,
                    ManagedModel.engine == engine.value,
                    ManagedModel.hf_repo == repo,
                )
            ).first()
            if existing is not None:
                existing.workload = workload.value
                existing.quant = quant
                if options is not None:
                    existing.launch_options = options.model_dump(mode="json")
                existing.updated_at = utcnow()
                session.add(existing)
                session.flush()
                session.refresh(existing)
                return existing
            row = ManagedModel(
                owner_id=owner_id,
                engine=engine.value,
                workload=workload.value,
                hf_repo=repo,
                quant=quant,
                state=ServeState.downloading.value,
                launch_options=(options or LaunchOptions()).model_dump(mode="json"),
            )
            session.add(row)
            session.flush()
            session.refresh(row)
            return row

        return await in_session(self._db, work)

    async def update(self, managed_id: str, **fields) -> None:
        def work(session: Session) -> None:
            row = session.get(ManagedModel, managed_id)
            if row is None:
                return
            for key, value in fields.items():
                setattr(row, key, value.value if isinstance(value, ServeState) else value)
            row.updated_at = utcnow()
            session.add(row)

        await in_session(self._db, work)

    @staticmethod
    def to_view(row: ManagedModel) -> ManagedModelView:
        return ManagedModelView(
            id=row.id,
            engine=EngineKind(row.engine),
            workload=Workload(row.workload),
            hf_repo=row.hf_repo,
            quant=row.quant,
            state=ServeState(row.state),
            endpoint_id=row.endpoint_id,
            port=row.port,
            last_error=row.last_error,
            options=launch_options(row),
        )
