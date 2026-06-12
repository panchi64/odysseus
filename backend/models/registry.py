"""Model role→endpoint registry schema.

A **role** (``main``, ``utility``, ``embedding``, later ``vision``/``image-gen``)
binds to an **ordered fallback chain** of endpoints. The chain is wrapped in
Pydantic AI's ``FallbackModel`` at resolution time, so a dead endpoint falls
through to the next.

An **endpoint** is a provider-agnostic OpenAI-compatible spec: a ``base_url`` +
``model`` name + optional key, plus the metadata the engine consumes — the
``context_window`` (feeds context reduction) and capability flags (native
tool-calling is required for the tool-driving roles, plus vision/thinking).

The **API key is the only sensitive field**: it is stored application-layer
encrypted (the chosen at-rest posture — whole-DB SQLCipher has no portable
3.14 wheels). Everything else is structural metadata the DB indexes in the clear.
The per-conversation ``main`` override is a runtime argument, not stored here.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel

from models._fields import new_id, utcnow


class ModelEndpoint(SQLModel, table=True):
    __tablename__ = "model_endpoints"
    # An operator's endpoint names are unique, so a chain can refer to them
    # stably and a re-import can't silently duplicate one.
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_endpoint_owner_name"),)

    id: str = Field(default_factory=new_id, primary_key=True)
    owner_id: str = Field(index=True)
    name: str
    base_url: str
    # The endpoint is a provider connection; ``model`` is the default/fallback used
    # when the chat picker doesn't override it and the provider's models API isn't
    # available. Optional — the picker discovers models from the provider at runtime.
    model: str | None = None
    # App-layer AEAD ciphertext of the API key; None ⇒ no key (local servers).
    api_key_enc: str | None = None
    context_window: int | None = None
    # AE-8.1: native tool-calling is required of the tool-driving roles. vision
    # and thinking gate other features (scanned-PDF extraction, reasoning split).
    native_tools: bool = True
    vision: bool = False
    thinking: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ModelRole(SQLModel, table=True):
    __tablename__ = "model_roles"
    __table_args__ = (UniqueConstraint("owner_id", "role", name="uq_role_owner_role"),)

    id: str = Field(default_factory=new_id, primary_key=True)
    owner_id: str = Field(index=True)
    role: str  # main | utility | embedding | vision | image-gen
    # The ordered fallback chain, by endpoint id. First is primary; the rest are
    # tried in order. Stored as JSON so order and length are one row, one write.
    endpoint_ids: list[str] = Field(sa_column=Column(JSON, nullable=False, default=list))
    updated_at: datetime = Field(default_factory=utcnow)
