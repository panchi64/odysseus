"""The model registry: role→chain resolution, encryption at rest, REST surface."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.openai import OpenAIChatModel

from core.db import init_db, make_engine
from core.exceptions import DegradedCapabilityError, NotFoundError
from core.vault import Vault
from services.registry import ModelRegistry

from ._helpers import client_app

OWNER = "operator"


async def _registry() -> ModelRegistry:
    """A registry on a throwaway in-memory DB with an unlocked vault."""
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    tmp = tempfile.mkdtemp()
    vault = Vault(Path(tmp) / "keyfile.json")
    await vault.setup("pw")
    return ModelRegistry(engine, vault)


async def test_single_endpoint_resolves_to_plain_model():
    reg = await _registry()
    ep = await reg.create_endpoint(
        OWNER, name="local", base_url="http://x/v1", model="qwen"
    )
    await reg.set_role(OWNER, "main", [ep.id])

    model = await reg.resolve("main", owner_id=OWNER)
    assert isinstance(model, OpenAIChatModel)
    assert not isinstance(model, FallbackModel)


async def test_multi_endpoint_chain_wraps_in_fallback():
    reg = await _registry()
    primary = await reg.create_endpoint(OWNER, name="a", base_url="http://a/v1", model="m1")
    backup = await reg.create_endpoint(OWNER, name="b", base_url="http://b/v1", model="m2")
    await reg.set_role(OWNER, "main", [primary.id, backup.id])

    model = await reg.resolve("main", owner_id=OWNER)
    assert isinstance(model, FallbackModel)
    assert len(model.models) == 2


async def test_unbound_utility_is_degraded():
    reg = await _registry()
    ep = await reg.create_endpoint(OWNER, name="main-ep", base_url="http://m/v1", model="m")
    await reg.set_role(OWNER, "main", [ep.id])
    # utility no longer inherits main's chain — an unbound utility is degraded;
    # the chat layer reuses the resolved main model instead.
    with pytest.raises(DegradedCapabilityError):
        await reg.resolve("utility", owner_id=OWNER)


async def test_bound_utility_resolves_independently():
    reg = await _registry()
    ep = await reg.create_endpoint(OWNER, name="util", base_url="http://u/v1", model="u")
    await reg.set_role(OWNER, "utility", [ep.id])
    model = await reg.resolve("utility", owner_id=OWNER)
    assert isinstance(model, OpenAIChatModel)


async def test_main_override_picks_a_specific_endpoint():
    reg = await _registry()
    default = await reg.create_endpoint(OWNER, name="d", base_url="http://d/v1", model="d")
    picked = await reg.create_endpoint(OWNER, name="p", base_url="http://p/v1", model="p")
    await reg.set_role(OWNER, "main", [default.id])

    model = await reg.resolve("main", owner_id=OWNER, override_endpoint_id=picked.id)
    assert isinstance(model, OpenAIChatModel)
    assert model.model_name == "p"


async def test_main_override_with_model_picks_that_model():
    reg = await _registry()
    # The endpoint is a bare provider connection (no baked model); the picker
    # supplies the specific model it discovered from the provider.
    ep = await reg.create_endpoint(OWNER, name="p", base_url="http://p/v1")
    model = await reg.resolve(
        "main", owner_id=OWNER, override_endpoint_id=ep.id, override_model="qwen-72b"
    )
    assert isinstance(model, OpenAIChatModel)
    assert model.model_name == "qwen-72b"


async def test_modelless_endpoint_without_override_is_degraded():
    reg = await _registry()
    ep = await reg.create_endpoint(OWNER, name="p", base_url="http://p/v1")
    await reg.set_role(OWNER, "main", [ep.id])
    # No baked model and no picker override → nothing to run.
    with pytest.raises(DegradedCapabilityError):
        await reg.resolve("main", owner_id=OWNER)


async def test_unconfigured_role_is_degraded():
    reg = await _registry()
    # No endpoints, no bindings → degraded; the registry is the only source of
    # truth, so there is no env (or other) fallback to rescue resolution.
    with pytest.raises(DegradedCapabilityError):
        await reg.resolve("main", owner_id=OWNER)
    with pytest.raises(DegradedCapabilityError):
        await reg.resolve("embedding", owner_id=OWNER)


async def test_api_key_is_encrypted_at_rest():
    reg = await _registry()
    ep = await reg.create_endpoint(
        OWNER, name="keyed", base_url="http://x/v1", model="m", api_key="super-secret"
    )
    assert ep.api_key_enc is not None
    assert "super-secret" not in ep.api_key_enc  # stored as ciphertext
    # And it round-trips on resolve: the built provider gets the plaintext key.
    await reg.set_role(OWNER, "main", [ep.id])
    model = await reg.resolve("main", owner_id=OWNER)
    assert isinstance(model, OpenAIChatModel)


async def test_tool_calling_role_rejects_non_tool_endpoint():
    reg = await _registry()
    ep = await reg.create_endpoint(
        OWNER, name="no-tools", base_url="http://x/v1", model="m", native_tools=False
    )
    with pytest.raises(ValueError, match="native tool-calling"):
        await reg.set_role(OWNER, "main", [ep.id])
    # An embedding role accepts it — tool-calling isn't required there.
    await reg.set_role(OWNER, "embedding", [ep.id])


async def test_unknown_endpoint_in_chain_is_not_found():
    reg = await _registry()
    with pytest.raises(NotFoundError):
        await reg.set_role(OWNER, "main", ["does-not-exist"])


# --- REST surface ---------------------------------------------------------


async def test_endpoint_crud_over_rest_hides_api_key():
    async with client_app() as (client, _app):
        resp = await client.post(
            "/models/endpoints",
            json={"name": "local", "base_url": "http://x/v1", "model": "m", "api_key": "k"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["has_api_key"] is True
        assert "api_key" not in body and "api_key_enc" not in body
        endpoint_id = body["id"]

        listing = (await client.get("/models/endpoints")).json()
        assert [e["id"] for e in listing] == [endpoint_id]

        # Bind it to the main role, then read the bindings back.
        put = await client.put("/models/roles/main", json={"endpoint_ids": [endpoint_id]})
        assert put.status_code == 204
        roles = (await client.get("/models/roles")).json()
        assert roles == {"main": [endpoint_id]}

        deleted = await client.delete(f"/models/endpoints/{endpoint_id}")
        assert deleted.status_code == 204
        assert (await client.get("/models/endpoints")).json() == []


async def test_rest_rejects_unknown_role_and_missing_endpoint():
    async with client_app() as (client, _app):
        bad_role = await client.put("/models/roles/nonsense", json={"endpoint_ids": []})
        assert bad_role.status_code == 422
        missing = await client.put("/models/roles/main", json={"endpoint_ids": ["nope"]})
        assert missing.status_code == 404


async def test_model_discovery_lists_provider_models(monkeypatch):
    async def fake_list(self, owner_id, endpoint_id):
        return ["gpt-4o", "gpt-4o-mini"]

    monkeypatch.setattr(ModelRegistry, "list_provider_models", fake_list)
    async with client_app() as (client, _app):
        ep = (
            await client.post(
                "/models/endpoints", json={"name": "local", "base_url": "http://x/v1"}
            )
        ).json()
        # The endpoint was created with no model — the picker discovers them.
        assert ep["model"] is None
        resp = await client.get(f"/models/endpoints/{ep['id']}/models")
        assert resp.status_code == 200
        assert resp.json() == {"models": ["gpt-4o", "gpt-4o-mini"], "supported": True}


async def test_model_discovery_degrades_when_provider_has_no_models_api(monkeypatch):
    async def fake_list(self, owner_id, endpoint_id):
        raise DegradedCapabilityError("no models API")

    monkeypatch.setattr(ModelRegistry, "list_provider_models", fake_list)
    async with client_app() as (client, _app):
        ep = (
            await client.post(
                "/models/endpoints", json={"name": "local", "base_url": "http://x/v1"}
            )
        ).json()
        resp = await client.get(f"/models/endpoints/{ep['id']}/models")
        assert resp.status_code == 200
        # Unsupported, not an error — the picker falls back to the configured model.
        assert resp.json() == {"models": [], "supported": False}


def test_extract_model_ids_handles_provider_shapes():
    from services.llm import _extract_model_ids

    # OpenAI / Anthropic: {"data": [{"id": …}]}
    assert _extract_model_ids({"data": [{"id": "b"}, {"id": "a"}]}) == ["a", "b"]
    # Gemini / Cohere / Ollama-native: {"models": [{"name": …}]}, "models/" stripped.
    assert _extract_model_ids({"models": [{"name": "models/gemini-1.5-pro"}]}) == [
        "gemini-1.5-pro"
    ]
    # The models/ strip is scoped to the named-models shape — an OpenAI-shaped id
    # that legitimately starts with models/ is preserved.
    assert _extract_model_ids({"data": [{"id": "models/foo"}]}) == ["models/foo"]
    # A name that is only the prefix strips to empty and is dropped, not offered.
    assert _extract_model_ids({"models": [{"name": "models/"}]}) == []
    # Bare list of strings, de-duplicated.
    assert _extract_model_ids(["qwen", "llama3", "qwen"]) == ["llama3", "qwen"]
    # Recognized shape that lists nothing → empty (supported but empty).
    assert _extract_model_ids({"object": "list", "data": []}) == []
    # Unrecognized payload → None (no models API), distinct from empty.
    assert _extract_model_ids({"foo": "bar"}) is None
