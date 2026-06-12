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


async def test_overview_counts_memories():
    async with client_app() as (client, app):
        await app.state.memory.remember("operator", "the operator prefers dark mode")
        resp = await client.get("/overview")
        body = resp.json()

    assert body["memory_count"] == 1
