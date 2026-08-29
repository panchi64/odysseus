"""Where a model's context window comes from.

The window is the number every limit-keeping mechanism measures against — the gauge
under the composer, auto-compaction's trigger, the overflow warning — so a thread whose
window is unknown has no working guard at all. It used to be a field the operator typed
in and usually didn't; it is now asked of the provider, with the field kept as the
override for providers that won't say.

Two rules carry the design and both are asserted here: an operator-set value always
wins over a discovered one, and a window that can't be established stops the turn
rather than letting it run unguarded.
"""

from __future__ import annotations

import httpx
import pytest

from core.vault import Vault
from services import llm
from services.providers.anthropic import PROVIDER as ANTHROPIC
from services.providers.google import PROVIDER as GOOGLE


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ── OpenAI-wire servers: no standard field, so several are read ──────────────────


@pytest.mark.parametrize(
    "key",
    ["context_length", "max_context_length", "max_model_len", "context_window", "n_ctx"],
)
async def test_reads_whichever_context_key_the_server_invented(key):
    # "OpenAI-compatible" agrees on the chat route and nothing else: the OpenAI
    # /v1/models schema has no context field at all, so every server that reports one
    # made up its own name. vLLM says max_model_len, llama.cpp n_ctx, and so on.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "m", key: 4096}]})

    async with _client(handler) as client:
        assert (
            await llm.discover_openai_context_window("http://server/v1", "m", client=client) == 4096
        )


async def test_falls_back_to_lm_studios_own_listing():
    # The most common local setup can't answer on the OpenAI route — LM Studio reports
    # no context there — but does on its native one. Without this fallback, discovery
    # would come back empty for the very endpoint it most needs to serve.
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "qwen"}]})
        assert request.url.path == "/api/v0/models"
        return httpx.Response(200, json={"data": [{"id": "qwen", "max_context_length": 262144}]})

    async with _client(handler) as client:
        assert (
            await llm.discover_openai_context_window("http://server/v1", "qwen", client=client)
            == 262144
        )


async def test_prefers_the_length_actually_loaded():
    # A model loaded at 32k in a server that *could* do 256k has a real ceiling of 32k.
    # The gauge has to measure the limit the next turn will hit, not the one the
    # hardware would allow.
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "qwen"}]})
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "qwen", "max_context_length": 262144, "loaded_context_length": 32768}
                ]
            },
        )

    async with _client(handler) as client:
        assert (
            await llm.discover_openai_context_window("http://server/v1", "qwen", client=client)
            == 32768
        )


async def test_only_the_asked_for_model_answers():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [{"id": "small", "n_ctx": 8192}, {"id": "big", "n_ctx": 131072}]},
        )

    async with _client(handler) as client:
        assert (
            await llm.discover_openai_context_window("http://s/v1", "big", client=client) == 131072
        )


async def test_a_server_that_says_nothing_yields_none_rather_than_raising():
    # Every caller's response to "couldn't establish it" is identical, so the failure
    # is collapsed here instead of at each call site.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "m"}]})

    async with _client(handler) as client:
        assert await llm.discover_openai_context_window("http://s/v1", "m", client=client) is None


async def test_an_unreachable_server_is_not_an_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    async with _client(handler) as client:
        assert await llm.discover_openai_context_window("http://s/v1", "m", client=client) is None


async def test_a_nonsense_value_is_ignored():
    # `True` is an `int` subclass — a server answering `"n_ctx": true` would otherwise
    # produce a one-token context window, and a gauge pinned at 100% forever.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "m", "n_ctx": True, "max_model_len": 0}]})

    async with _client(handler) as client:
        assert await llm.discover_openai_context_window("http://s/v1", "m", client=client) is None


# ── The providers that state it, and the one that doesn't ────────────────────────


async def test_gemini_reports_its_input_limit():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "models": [
                    {"name": "models/gemini-x", "inputTokenLimit": 1048576},
                    {"name": "models/other", "inputTokenLimit": 32768},
                ]
            },
        )

    async with _client(handler) as client:
        assert await GOOGLE.context_window("https://g", "key", "gemini-x", client=client) == 1048576


async def test_anthropic_admits_it_cannot_say():
    # Deliberately not a table of known Anthropic windows: such a table is correct
    # until a new model or an extended-context beta makes it silently wrong, and a
    # gauge that is confidently wrong is worse than one that defers to the operator.
    assert await ANTHROPIC.context_window("https://a", "key", "claude-x") is None


# ── Resolution: precedence, caching, and the gate ────────────────────────────────


async def _registry(tmp_path, monkeypatch, *, window: int | None):
    """A registry whose stub provider reports ``window``."""
    from pydantic_ai.models.test import TestModel

    from core.db import init_db, make_engine
    from services import providers
    from services.registry import ModelRegistry

    class _Stub:
        id = "probe-stub"
        display_name = "Probe stub"
        requires_key = False
        asked = 0

        async def context_window(self, base_url, api_key, model, *, client=None):
            type(self).asked += 1
            return window

        # Enough of the rest of the contract for a full resolve to run: the gate test
        # goes through `resolve_detailed`, which builds a model and asks the adapter
        # how to quiet its reasoning before it ever reaches the window check.
        def build_model(self, spec):
            return TestModel(custom_output_text="ok")

        def reasoning_off(self, descriptor):
            return {}

    _Stub.asked = 0
    registry_map = dict(providers._registry())
    registry_map["probe-stub"] = _Stub()
    monkeypatch.setattr(providers, "_PROVIDERS", registry_map)

    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    vault = Vault(tmp_path / "keyfile.json")
    await vault.setup("pw")
    return ModelRegistry(engine, vault), _Stub


async def _bind(registry, *, context_window: int | None):
    endpoint = await registry.create_endpoint(
        "operator",
        name="stub",
        base_url="http://stub/v1",
        provider="probe-stub",
        model="stub-model",
        context_window=context_window,
    )
    await registry.set_role("operator", "main", [endpoint.id])
    return endpoint


async def test_a_discovered_window_reaches_resolution(tmp_path, monkeypatch):
    registry, _ = await _registry(tmp_path, monkeypatch, window=200_000)
    await _bind(registry, context_window=None)
    assert await registry.main_context_window("operator") == 200_000


async def test_the_operators_own_value_wins(tmp_path, monkeypatch):
    # The field is the override for providers that can't answer, so a discovered value
    # silently replacing a deliberate one would make the setting appear not to work.
    registry, stub = await _registry(tmp_path, monkeypatch, window=200_000)
    await _bind(registry, context_window=8192)
    assert await registry.main_context_window("operator") == 8192
    assert stub.asked == 0  # not even consulted


async def test_the_provider_is_asked_once_and_then_remembered(tmp_path, monkeypatch):
    # This sits on the path of every turn; an uncached lookup would put a provider
    # round-trip in front of each one for a number already known.
    registry, stub = await _registry(tmp_path, monkeypatch, window=200_000)
    await _bind(registry, context_window=None)
    for _ in range(3):
        assert await registry.main_context_window("operator") == 200_000
    assert stub.asked == 1


async def test_editing_an_endpoint_re_asks(tmp_path, monkeypatch):
    # A write can move the base URL, the model or the operator's own value — every
    # input the memo keyed on — so it drops rather than being reasoned about.
    registry, stub = await _registry(tmp_path, monkeypatch, window=200_000)
    endpoint = await _bind(registry, context_window=None)
    await registry.main_context_window("operator")
    await registry.update_endpoint("operator", endpoint.id, name="renamed")
    await registry.main_context_window("operator")
    assert stub.asked == 2


async def test_a_provider_that_says_nothing_leaves_the_window_unknown(tmp_path, monkeypatch):
    registry, _ = await _registry(tmp_path, monkeypatch, window=None)
    await _bind(registry, context_window=None)
    assert await registry.main_context_window("operator") is None


async def test_a_turn_is_refused_when_no_window_can_be_established(tmp_path, monkeypatch):
    """The gate. Without a window every guard that keeps a thread inside its limit is
    inert, so the turn stops here — with a message naming the fix — instead of running
    normally until the provider rejects it outright."""
    from fastapi import HTTPException

    from routes.chat import resolve_turn_models

    registry, _ = await _registry(tmp_path, monkeypatch, window=None)
    await _bind(registry, context_window=None)

    with pytest.raises(HTTPException) as caught:
        await resolve_turn_models(registry, None, None, owner_id="operator")
    assert caught.value.status_code == 422
    assert "context window" in caught.value.detail


# ── The binding: what the frontend reads to know a window exists ─────────────────


async def test_the_window_follows_the_binding_not_the_endpoint_row(tmp_path, monkeypatch):
    """The bug the send gate shipped with. An endpoint row carries only a *default*
    model and usually doesn't set one — the model in play is the one the role pinned. A
    window read off the endpoint alone therefore answers null on exactly this workspace's
    shape (one server, many models, the choice made in the picker), which had the
    composer refusing to send on a perfectly configured thread."""
    registry, _ = await _registry(tmp_path, monkeypatch, window=262_144)
    endpoint = await registry.create_endpoint(
        "operator", name="stub", base_url="http://stub/v1", provider="probe-stub"
    )
    # No default model on the row — the binding names it, exactly as the picker leaves it.
    assert endpoint.model is None
    await registry.set_role("operator", "main", [endpoint.id], model="stub-model")

    assert await registry.role_context_window("operator", "main") == 262_144


async def test_every_role_reports_its_own_window(tmp_path, monkeypatch):
    """The field means the same thing on every row of the roles listing — a value
    populated for one role and silently null for the others is a trap for the next
    caller."""
    registry, _ = await _registry(tmp_path, monkeypatch, window=200_000)
    await _bind(registry, context_window=None)
    assert await registry.role_context_window("operator", "main") == 200_000
    # Unconfigured roles answer null rather than raising: this is a read path.
    assert await registry.role_context_window("operator", "utility") is None


async def test_main_context_window_is_the_same_answer(tmp_path, monkeypatch):
    """The gate calls one, the roles listing the other. If they could disagree, the
    operator would meet a refusal from a composer that looked ready — or be blocked on a
    thread that would have run fine."""
    registry, _ = await _registry(tmp_path, monkeypatch, window=262_144)
    await _bind(registry, context_window=None)
    assert await registry.main_context_window("operator") == await registry.role_context_window(
        "operator", "main"
    )


async def test_an_unresolvable_role_reports_no_window_rather_than_raising(tmp_path, monkeypatch):
    registry, _ = await _registry(tmp_path, monkeypatch, window=None)
    await _bind(registry, context_window=None)
    assert await registry.role_context_window("operator", "main") is None
