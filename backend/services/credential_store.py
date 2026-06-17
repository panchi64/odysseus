"""Outbound service credentials — the store behind the API Tokens page.

Holds the API keys the system calls *outbound* services with (the Cookbook's quality
benchmarks + its HuggingFace token), sealed with the vault exactly like the model-endpoint
/ search-provider `api_key`. The set of services is a **static catalog** (`KNOWN_SERVICES`)
— the system declares which integrations it has; the store only holds a key per known
service. A read returns ``None`` while the vault is locked so callers degrade to their env
fallback rather than crashing at boot.

Raises domain errors only (`NotFoundError`); the route maps to HTTP.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Engine
from sqlmodel import Session, select

from core.db import in_session
from core.exceptions import NotFoundError
from core.vault import Vault, VaultLocked
from models.service_credential import ServiceCredential

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ServiceInfo:
    """A declared outbound integration the operator can supply a key for."""

    id: str
    label: str
    purpose: str
    docs_url: str


# The outbound services the system integrates with. Display metadata lives here (not the
# DB); a key is stored per id. Extend this as new keyed integrations land.
KNOWN_SERVICES: tuple[ServiceInfo, ...] = (
    ServiceInfo(
        "artificial_analysis",
        "Artificial Analysis",
        "Cookbook model-quality ranking — the Intelligence Index, fast to cover new models.",
        "https://artificialanalysis.ai/",
    ),
    ServiceInfo(
        "llm_stats",
        "llm-stats.com",
        "Cookbook model-quality ranking — broad, fast-moving benchmark coverage.",
        "https://llm-stats.com/",
    ),
    ServiceInfo(
        "huggingface",
        "Hugging Face",
        "Cookbook model catalog — an access token lifts the anonymous API rate limit.",
        "https://huggingface.co/settings/tokens",
    ),
)
_SERVICE_IDS = frozenset(s.id for s in KNOWN_SERVICES)


class CredentialStore:
    def __init__(self, engine: Engine, vault: Vault) -> None:
        self._engine = engine
        self._vault = vault
        self._on_change: list[Callable[[], None]] = []

    @staticmethod
    def known_services() -> tuple[ServiceInfo, ...]:
        return KNOWN_SERVICES

    def on_change(self, callback: Callable[[], None]) -> None:
        """Register a callback fired after any credential write (set/clear) — e.g. the
        Cookbook invalidates its catalog so a new key applies without a restart."""
        self._on_change.append(callback)

    def _fire_change(self) -> None:
        for callback in self._on_change:
            try:
                callback()
            except Exception:
                logger.warning("credentials: on_change callback failed", exc_info=True)

    async def status(self, owner_id: str) -> dict[str, bool]:
        """``service id`` → whether a key is stored (no decryption — just presence)."""

        def work(session: Session) -> dict[str, bool]:
            rows = session.exec(
                select(ServiceCredential).where(ServiceCredential.owner_id == owner_id)
            ).all()
            return {row.service: row.api_key_enc is not None for row in rows}

        return await in_session(self._engine, work)

    async def set_key(self, owner_id: str, service: str, api_key: str) -> None:
        """Seal and upsert the key for a known service. An empty key clears it."""
        if service not in _SERVICE_IDS:
            raise NotFoundError(f"unknown service {service!r}")
        if not api_key:
            await self.clear_key(owner_id, service)
            return
        enc = self._vault.encrypt_str(api_key)

        def work(session: Session) -> None:
            row = session.exec(
                select(ServiceCredential).where(
                    ServiceCredential.owner_id == owner_id,
                    ServiceCredential.service == service,
                )
            ).first()
            if row is None:
                row = ServiceCredential(owner_id=owner_id, service=service, api_key_enc=enc)
            else:
                row.api_key_enc = enc
                row.updated_at = datetime.now(UTC)
            session.add(row)
            session.flush()

        await in_session(self._engine, work)
        self._fire_change()

    async def clear_key(self, owner_id: str, service: str) -> None:
        if service not in _SERVICE_IDS:
            raise NotFoundError(f"unknown service {service!r}")

        def work(session: Session) -> None:
            row = session.exec(
                select(ServiceCredential).where(
                    ServiceCredential.owner_id == owner_id,
                    ServiceCredential.service == service,
                )
            ).first()
            if row is not None:
                session.delete(row)

        await in_session(self._engine, work)
        self._fire_change()

    async def get_secret(self, owner_id: str, service: str) -> str | None:
        """The decrypted key for a service, or ``None`` when unset **or the vault is
        locked** — so consumers (the Cookbook) degrade to their env fallback at boot
        instead of raising."""
        if not self._vault.is_unlocked:
            return None

        def work(session: Session) -> str | None:
            row = session.exec(
                select(ServiceCredential).where(
                    ServiceCredential.owner_id == owner_id,
                    ServiceCredential.service == service,
                )
            ).first()
            return row.api_key_enc if row is not None else None

        enc = await in_session(self._engine, work)
        if not enc:
            return None
        try:
            return self._vault.decrypt_str(enc)
        except VaultLocked:
            return None
