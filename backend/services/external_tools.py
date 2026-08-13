"""The shared layer under both external tool sources: how a tool is *named* and what the
operator has *decided* about it.

One policy store behind both external sources — MCP servers (`MCP-*`) and third-party
connectors (`INTEG-*`) — because the operator's two decisions about such a tool are the
same in both cases:

- **enabled** — is it offered to the agent at all (`MCP-1`, `AE-3.3`);
- **trusted** — may it run without pausing for approval (`AE-3.6`).

Both are keyed **per tool**. Enabling a server or configuring a connector says nothing
about what any individual tool on it does, so neither may imply trust; a server-level
flag would auto-approve tools the operator has never seen. Trust is granted one tool at a
time and revoked the same way.

A *missing* row is the safe default — ``enabled=True, trusted=False`` — so a tool the
server only just started exposing is usable but approval-gated, never silently trusted.

Policy, not content: nothing here is vault-sealed, exactly as ``ApprovalGrant`` isn't, so
it stays indexable and readable while the vault is locked. Raises domain errors only.

This module also holds the :class:`ExternalRuntime` handle — see its docstring for why the
external category reaches its services through a process-level handle rather than through
``RunDeps`` like every other capability.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from services.integrations import IntegrationService
    from services.mcp import McpRegistry

from sqlalchemy import Engine, delete
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from core.db import in_session
from core.exceptions import NotFoundError
from models._fields import new_id, utcnow
from models.external_tool import ExternalToolPolicy

SourceKind = Literal["mcp", "integration"]

# The default an unseen tool gets: offered to the agent, but approval-gated (`AE-3.6`).
DEFAULT_ENABLED = True
DEFAULT_TRUSTED = False

_NON_NAME_CHARS = re.compile(r"[^a-z0-9]+")


def tool_slug(label: str) -> str:
    """The operator's label reduced to a tool-name-safe prefix.

    Every external tool the model sees is named ``external_{slug}_{tool}``, so the slug
    has to survive being pasted into an identifier: lowercase, alphanumerics and
    underscores, never leading with a digit. A label that reduces to nothing (emoji,
    CJK-only) falls back to ``source`` and the caller's uniqueness check disambiguates it.
    """
    slug = _NON_NAME_CHARS.sub("_", label.strip().lower()).strip("_")
    if not slug:
        return "source"
    return f"s_{slug}" if slug[0].isdigit() else slug


@dataclass(frozen=True)
class ToolPolicy:
    """The operator's decision about one external tool."""

    enabled: bool = DEFAULT_ENABLED
    trusted: bool = DEFAULT_TRUSTED


class ExternalPolicyStore:
    def __init__(self, db_engine: Engine) -> None:
        self._db = db_engine

    async def snapshot(
        self, owner_id: str, source_kind: SourceKind, source_id: str
    ) -> dict[str, ToolPolicy]:
        """Every recorded decision for one source, keyed by the tool's own name. Tools
        with no row simply aren't in the map — the caller applies the default."""

        def work(session: Session) -> dict[str, ToolPolicy]:
            rows = session.exec(
                select(ExternalToolPolicy)
                .where(ExternalToolPolicy.owner_id == owner_id)
                .where(ExternalToolPolicy.source_kind == source_kind)
                .where(ExternalToolPolicy.source_id == source_id)
            ).all()
            return {r.tool_name: ToolPolicy(enabled=r.enabled, trusted=r.trusted) for r in rows}

        return await in_session(self._db, work)

    async def get(
        self, owner_id: str, source_kind: SourceKind, source_id: str, tool_name: str
    ) -> ToolPolicy:
        """One tool's policy, falling back to the default when it has no row yet. This is
        the read the trust gate makes on every external tool call, so it is deliberately a
        fresh read: revoking trust must take effect on the next call, not the next run."""

        def work(session: Session) -> ToolPolicy:
            row = session.exec(
                select(ExternalToolPolicy)
                .where(ExternalToolPolicy.owner_id == owner_id)
                .where(ExternalToolPolicy.source_kind == source_kind)
                .where(ExternalToolPolicy.source_id == source_id)
                .where(ExternalToolPolicy.tool_name == tool_name)
            ).first()
            if row is None:
                return ToolPolicy()
            return ToolPolicy(enabled=row.enabled, trusted=row.trusted)

        return await in_session(self._db, work)

    async def set(
        self,
        owner_id: str,
        source_kind: SourceKind,
        source_id: str,
        tool_name: str,
        *,
        enabled: bool | None = None,
        trusted: bool | None = None,
    ) -> ToolPolicy:
        """Record (or amend) the operator's decision about one tool. Only the fields
        passed are changed, so toggling ``enabled`` never disturbs ``trusted``.

        Marking a tool trusted is an operator action — never the agent's — and revoking
        it is the same call with ``trusted=False``, which puts the tool straight back to
        per-call approval.
        """
        if enabled is None and trusted is None:
            return await self.get(owner_id, source_kind, source_id, tool_name)
        now = utcnow()

        def work(session: Session) -> ToolPolicy:
            # Atomic upsert over uq_external_tool_policy_scope — a plain
            # select-then-insert races two concurrent toggles of the same tool into a
            # duplicate-insert IntegrityError, so the conflict is resolved in the DB.
            values = {
                "id": new_id(),
                "owner_id": owner_id,
                "source_kind": source_kind,
                "source_id": source_id,
                "tool_name": tool_name,
                "enabled": DEFAULT_ENABLED if enabled is None else enabled,
                "trusted": DEFAULT_TRUSTED if trusted is None else trusted,
                "created_at": now,
                "updated_at": now,
            }
            updates: dict[str, object] = {"updated_at": now}
            if enabled is not None:
                updates["enabled"] = enabled
            if trusted is not None:
                updates["trusted"] = trusted
            session.execute(
                sqlite_insert(ExternalToolPolicy)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=["owner_id", "source_kind", "source_id", "tool_name"],
                    set_=updates,
                )
            )
            row = session.exec(
                select(ExternalToolPolicy)
                .where(ExternalToolPolicy.owner_id == owner_id)
                .where(ExternalToolPolicy.source_kind == source_kind)
                .where(ExternalToolPolicy.source_id == source_id)
                .where(ExternalToolPolicy.tool_name == tool_name)
            ).first()
            if row is None:  # pragma: no cover - the upsert above just wrote it
                raise NotFoundError(f"policy for tool {tool_name!r} could not be written")
            return ToolPolicy(enabled=row.enabled, trusted=row.trusted)

        return await in_session(self._db, work)

    async def forget_source(
        self, owner_id: str, source_kind: SourceKind, source_id: str
    ) -> None:
        """Drop every decision for a source — called when its server/connector is
        removed, so a later registration at the same id can't inherit stale trust."""

        def work(session: Session) -> None:
            session.execute(
                delete(ExternalToolPolicy)
                .where(ExternalToolPolicy.owner_id == owner_id)
                .where(ExternalToolPolicy.source_kind == source_kind)
                .where(ExternalToolPolicy.source_id == source_id)
            )

        await in_session(self._db, work)


@dataclass
class ExternalRuntime:
    """The two external-tool services, reachable by the toolset that surfaces them.

    Every other capability reaches its tools through ``RunDeps`` — the deliberate rule
    that a tool never uses a module global. The external category is the one place that
    cannot: its tools are not a fixed catalog but whatever the operator's servers and
    connectors happen to expose, so the category toolset has to read the registry *while
    composing a run*, and ``RunDeps`` is assembled by the run's caller before that point.

    So the two services live behind one process-level handle instead, set once when they
    are built. It is a single-operator, single-process backend, so this is a wiring seam
    rather than shared mutable state: the handle is written at construction and read
    thereafter. Unset ⇒ the external category simply contributes no tools, exactly like
    any other absent capability.
    """

    mcp: McpRegistry | None = None
    integrations: IntegrationService | None = None


_runtime = ExternalRuntime()


def set_external_runtime(
    *,
    mcp: McpRegistry | None = None,
    integrations: IntegrationService | None = None,
) -> None:
    """Publish a service to the external toolset. Each argument is applied only when
    given, so the MCP registry and the integration service can be wired independently."""
    if mcp is not None:
        _runtime.mcp = mcp
    if integrations is not None:
        _runtime.integrations = integrations


def external_runtime() -> ExternalRuntime:
    """The current handle. Never ``None`` — an unwired field is, which the caller treats
    as an absent capability."""
    return _runtime


def reset_external_runtime() -> None:
    """Drop both services — for tests, so one case's registry can't leak into the next."""
    _runtime.mcp = None
    _runtime.integrations = None
