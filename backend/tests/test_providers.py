"""The provider layer: adapter dispatch, save-time validation, and the migration that
backfills the legacy name-prefix inference into a real ``provider`` column."""

from __future__ import annotations

import pytest
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.openai import OpenAIChatModel
from sqlmodel import Session, text

from core.db import make_engine
from services import llm
from services.providers import all_providers, get_provider
from tests.test_registry import _registry, _resolve

from ._helpers import client_app

OWNER = "operator"


# --- the adapter registry --------------------------------------------------


def test_builtin_providers_are_discovered():
    ids = {p.id for p in all_providers()}
    assert {"openai-compatible", "anthropic", "google"} <= ids


def test_unknown_provider_raises():
    with pytest.raises(LookupError):
        get_provider("no-such-lab")


def test_build_model_dispatches_to_the_native_classes():
    """The whole point of the layer: a provider id selects the concrete Pydantic AI
    model class, so a lab's native protocol is spoken natively."""
    cases = [
        ("openai-compatible", OpenAIChatModel),
        ("anthropic", AnthropicModel),
        ("google", GoogleModel),
    ]
    for provider_id, model_cls in cases:
        spec = llm.EndpointSpec(
            base_url="https://api.example.com",
            model="some-model",
            provider=provider_id,
            api_key="k",
        )
        assert isinstance(llm.build_model(spec), model_cls), provider_id


async def test_openai_wire_carries_one_leading_system_message():
    """The standing prompt and the per-turn instructions both ride the OpenAI wire as
    system messages at the head. Hosted APIs take two; a self-hosted server hands the list
    to the model's own chat template, and the Qwen family's raises "System message must be
    at the beginning." on the second — so the adapter merges them into one. Asserted on
    the mapped wire messages (the library's private mapper) because the profile flag
    alone wouldn't catch the day the library renames or re-scopes it."""
    from pydantic_ai import ModelRequest, SystemPromptPart, UserPromptPart
    from pydantic_ai.models import ModelRequestParameters

    history = [
        ModelRequest(
            parts=[SystemPromptPart(content="IDENTITY"), UserPromptPart(content="hi")],
            instructions="RULES",
        )
    ]
    spec = llm.EndpointSpec(
        base_url="http://127.0.0.1:8080/v1",
        model="Qwen3-30B",
        provider="openai-compatible",
        api_key=None,
    )
    model = llm.build_model(spec)
    mapped = await model._map_messages(history, ModelRequestParameters())
    assert [m["role"] for m in mapped] == ["system", "user"]
    assert mapped[0]["content"] == "IDENTITY\n\nRULES"


def test_reasoning_off_is_provider_shaped():
    from services.reasoning import ModelDescriptor

    # OpenAI-compat falls back to the model-name heuristics.
    openai = get_provider("openai-compatible")
    assert openai.reasoning_off(ModelDescriptor(model_id="qwen-3")) != {}
    assert openai.reasoning_off(ModelDescriptor(model_id="llama-3.1-70b")) == {}
    # Anthropic thinking is opt-in per request — nothing to turn off.
    assert get_provider("anthropic").reasoning_off(ModelDescriptor(model_id="claude-x")) == {}
    # Only the Gemini Flash/Lite family accepts a zero budget; Pro rejects it.
    google = get_provider("google")
    assert google.reasoning_off(ModelDescriptor(model_id="gemini-2.5-flash")) == {
        "google_thinking_config": {"thinking_budget": 0}
    }
    assert google.reasoning_off(ModelDescriptor(model_id="gemini-2.5-pro")) == {}


# --- save-time validation ---------------------------------------------------


async def test_key_requiring_provider_rejects_a_keyless_save():
    reg = await _registry()
    with pytest.raises(ValueError):
        await reg.create_endpoint(
            OWNER, name="a", base_url="https://api.anthropic.com", provider="anthropic"
        )
    # And clearing the key out from under one is rejected the same way.
    ep = await reg.create_endpoint(
        OWNER,
        name="b",
        base_url="https://api.anthropic.com",
        provider="anthropic",
        model="claude-x",
        api_key="sk-ant-k",
    )
    with pytest.raises(ValueError):
        await reg.update_endpoint(OWNER, ep.id, api_key="")
    # Switching a keyless endpoint onto a key-requiring provider is rejected too.
    keyless = await reg.create_endpoint(OWNER, name="c", base_url="http://x/v1", model="m")
    with pytest.raises(ValueError):
        await reg.update_endpoint(OWNER, keyless.id, provider="google")


async def test_unknown_provider_rejected_at_save():
    reg = await _registry()
    with pytest.raises(ValueError):
        await reg.create_endpoint(OWNER, name="a", base_url="http://x/v1", provider="no-such-lab")


async def test_provider_flows_into_the_resolved_spec():
    reg = await _registry()
    ep = await reg.create_endpoint(
        OWNER,
        name="claude",
        base_url="https://api.anthropic.com",
        provider="anthropic",
        model="claude-x",
        api_key="sk-ant-k",
    )
    await reg.set_role(OWNER, "main", [ep.id])
    model = await _resolve(reg, "main", owner_id=OWNER)
    assert isinstance(model, AnthropicModel)


# --- the surface --------------------------------------------------------------


async def test_providers_route_serves_the_presets():
    async with client_app() as (client, _app):
        rows = (await client.get("/models/providers")).json()
        by_id = {row["id"]: row for row in rows}
        assert {"openai-compatible", "anthropic", "google"} <= set(by_id)
        anthropic = by_id["anthropic"]
        assert anthropic["requires_key"] is True
        assert anthropic["default_base_url"] == "https://api.anthropic.com"
        assert by_id["openai-compatible"]["requires_key"] is False


async def test_endpoint_routes_carry_and_validate_provider():
    async with client_app() as (client, _app):
        rejected = await client.post(
            "/models/endpoints",
            json={"name": "a", "base_url": "https://api.anthropic.com", "provider": "anthropic"},
        )
        assert rejected.status_code == 422

        created = await client.post(
            "/models/endpoints",
            json={
                "name": "a",
                "base_url": "https://api.anthropic.com",
                "provider": "anthropic",
                "model": "claude-x",
                "api_key": "sk-ant-k",
            },
        )
        assert created.status_code == 201
        body = created.json()
        assert body["provider"] == "anthropic"

        # Default provider when unspecified.
        plain = (
            await client.post("/models/endpoints", json={"name": "b", "base_url": "http://x/v1"})
        ).json()
        assert plain["provider"] == "openai-compatible"


# --- the migration's backfill -------------------------------------------------


def test_migration_backfills_local_prefix_endpoints():
    """Build the DB at the pre-provider revision, insert a locally-served endpoint the
    old way (its provider inferable only from a "Local · " name prefix, liveness
    overloaded onto `enabled`), upgrade to head, and assert the backfill turned that
    inference into a real `provider` column — and handed `enabled` back to the
    operator."""
    from alembic import command
    from alembic.config import Config

    from core.db import _ALEMBIC_INI

    engine = make_engine("sqlite:///:memory:")
    config = Config(str(_ALEMBIC_INI))
    config.attributes["connection"] = engine
    command.upgrade(config, "5a07sec0007")

    with Session(engine) as session:
        session.exec(
            text(
                "INSERT INTO model_endpoints "
                "(id, owner_id, name, base_url, enabled, native_tools, vision, thinking, "
                "created_at, updated_at) VALUES "
                "('e1', 'op', 'Local · acme/m', 'http://127.0.0.1:9/v1', 0, 1, 0, 0, "
                "'2026-01-01', '2026-01-01'), "
                "('e2', 'op', 'My cloud', 'https://api.example.com/v1', 1, 1, 0, 0, "
                "'2026-01-01', '2026-01-01')"
            )
        )
        session.commit()

    command.upgrade(config, "head")

    columns = "provider, enabled"
    with Session(engine) as session:
        local = session.exec(text(f"SELECT {columns} FROM model_endpoints WHERE id='e1'")).one()
        cloud = session.exec(text(f"SELECT {columns} FROM model_endpoints WHERE id='e2'")).one()
    # The row that was off only because it wasn't running: `enabled` handed back on, and
    # the retired `local` provider folded into the OpenAI-compatible one it always was.
    assert tuple(local) == ("openai-compatible", 1)
    assert tuple(cloud) == ("openai-compatible", 1)
