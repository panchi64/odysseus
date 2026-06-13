"""Home overview aggregate: real counts + backend-decided capability health."""

from __future__ import annotations

from ._helpers import client_app


def _capabilities(body) -> dict[str, dict]:
    return {c["key"]: c for c in body["capabilities"]}


async def test_overview_empty_workspace():
    """A fresh workspace: no endpoints/roles/conversations/memories. Main model is
    unconfigured (critical alert), embeddings degrade to keyword, and the sandbox
    is absent in tests — all reported, none fabricated."""
    async with client_app() as (client, _app):
        resp = await client.get("/overview")
        assert resp.status_code == 200
        body = resp.json()

    assert body["main_model"] is None
    assert body["endpoint_count"] == 0
    assert body["conversation_count"] == 0
    assert body["memory_count"] == 0
    assert body["active_run_count"] == 0

    caps = _capabilities(body)
    assert caps["main_model"]["status"] == "alert"
    assert caps["main_model"]["critical"] is True
    assert caps["main_model"]["remediation_href"] == "/models/cookbook"
    assert caps["embeddings"]["status"] == "warn"
    assert caps["sandbox"]["status"] == "warn"
    # Web search is managed (auto-run SearXNG); with no runtime in tests it degrades
    # to warn, and there is nothing for the operator to configure.
    assert caps["web_search"]["status"] == "warn"
    assert caps["web_search"]["detail"] == "no runtime — disabled"
    assert caps["web_search"]["remediation_href"] is None


async def test_overview_web_search_nominal_once_a_provider_is_enabled():
    async with client_app() as (client, app):
        await app.state.search.create_provider(
            "operator", name="searx", base_url="http://searx.local", enabled=True
        )
        body = (await client.get("/overview")).json()

    web = _capabilities(body)["web_search"]
    assert web["status"] == "nominal"
    assert web["detail"] == "SearXNG configured"


async def test_overview_reports_configured_main_model():
    async with client_app() as (client, app):
        endpoint = await app.state.models.create_endpoint(
            "operator",
            name="Local",
            base_url="http://localhost:1234/v1",
            model="qwen2.5-32b",
            context_window=32768,
        )
        await app.state.models.set_role("operator", "main", [endpoint.id])

        resp = await client.get("/overview")
        assert resp.status_code == 200
        body = resp.json()

    assert body["main_model"] == "qwen2.5-32b"
    assert body["main_provider"] == "Local"
    assert body["context_window"] == 32768
    assert body["endpoint_count"] == 1

    main = _capabilities(body)["main_model"]
    assert main["status"] == "nominal"
    assert main["detail"] == "qwen2.5-32b"


async def test_overview_counts_memories_and_conversations():
    async with client_app() as (client, app):
        await app.state.memory.remember("operator", "the operator prefers dark mode")
        await app.state.memory.remember("operator", "the operator's name is Frank")
        await app.state.conversations.create_conversation("operator")
        await app.state.conversations.create_conversation("operator")
        await app.state.conversations.create_conversation("operator")
        resp = await client.get("/overview")
        body = resp.json()

    assert body["memory_count"] == 2
    assert body["conversation_count"] == 3
