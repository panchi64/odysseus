"""Web capability: provider CRUD + encryption, SearXNG search, guarded fetch, and
the agent reaching it through the toolset stack."""

from __future__ import annotations

import ipaddress
import socket
import tempfile
from pathlib import Path

import httpx
import pytest
from sqlmodel import Session

from core.db import init_db, make_engine
from core.exceptions import DegradedCapabilityError, SSRFError, WebFetchError
from core.vault import Vault
from models.search import SearchProvider
from services.search import SearchService

OWNER = "operator"

_ARTICLE = """<html><head><title>Edible Plants</title></head><body><article>
<h1>Foraging Guide</h1>
<p>The dandelion is entirely edible, from root to flower, and grows almost everywhere.</p>
<p>Always positively identify a plant before eating any part of it in the wild.</p>
</article></body></html>"""


def _fake_getaddrinfo(host, port, *args, **kwargs):
    """Resolve IP literals to themselves, anything else to a fixed public IP — so
    redirect-to-private is exercised while hostnames stay offline-safe."""
    try:
        ip = str(ipaddress.ip_address(host))
    except ValueError:
        ip = "93.184.216.34"
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port or 0))]


async def _make_service(handler, **bounds) -> SearchService:
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    tmp = tempfile.mkdtemp()
    vault = Vault(Path(tmp) / "keyfile.json")
    await vault.setup("pw")
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    return SearchService(engine, vault, http_client=client, **bounds)


# --- provider catalog + encryption ----------------------------------------


async def test_provider_crud_and_api_key_encrypted_at_rest():
    svc = await _make_service(lambda req: httpx.Response(200))
    created = await svc.create_provider(
        OWNER, name="local-searx", base_url="http://searx.local", api_key="s3cret"
    )
    assert created.api_key_enc is not None and created.api_key_enc != "s3cret"

    # The plaintext key never lands in the column.
    with Session(svc._engine) as session:
        row = session.get(SearchProvider, created.id)
        assert "s3cret" not in (row.api_key_enc or "")
    assert svc._vault.decrypt_str(created.api_key_enc) == "s3cret"

    listed = await svc.list_providers(OWNER)
    assert [p.id for p in listed] == [created.id]

    await svc.update_provider(OWNER, created.id, enabled=False)
    assert (await svc.get_provider(OWNER, created.id)).enabled is False

    await svc.delete_provider(OWNER, created.id)
    assert await svc.list_providers(OWNER) == []


async def test_search_unconfigured_is_degraded():
    svc = await _make_service(lambda req: httpx.Response(200))
    with pytest.raises(DegradedCapabilityError):
        await svc.search(OWNER, "anything")


async def test_search_uses_managed_instance_when_no_provider():
    # Zero operator config: the backend's managed SearXNG is queried automatically.
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(
            200, json={"results": [{"title": "M", "url": "https://m.example", "content": "c"}]}
        )

    svc = await _make_service(handler, managed_url=lambda: "http://managed.local")
    results = await svc.search(OWNER, "q")
    assert seen["url"].startswith("http://managed.local/search")
    assert [r.title for r in results] == ["M"]


async def test_enabled_provider_overrides_managed_instance():
    # An operator-configured provider wins over the managed default.
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"results": []})

    svc = await _make_service(handler, managed_url=lambda: "http://managed.local")
    await svc.create_provider(OWNER, name="searx", base_url="http://override.local")
    await svc.search(OWNER, "q")
    assert seen["url"].startswith("http://override.local/search")


async def test_search_degraded_when_managed_not_ready_and_no_provider():
    # Managed instance still booting (URL None) and no provider ⇒ degrade cleanly.
    svc = await _make_service(lambda req: httpx.Response(200), managed_url=lambda: None)
    with pytest.raises(DegradedCapabilityError):
        await svc.search(OWNER, "q")


# --- search -----------------------------------------------------------------


async def test_search_maps_searxng_json_and_wraps_snippets():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "results": [
                    {"title": "First", "url": "https://a.example", "content": "snippet one"},
                    {"title": "Second", "url": "https://b.example", "content": "snippet two"},
                ]
            },
        )

    svc = await _make_service(handler)
    await svc.create_provider(OWNER, name="searx", base_url="http://searx.local")
    results = await svc.search(OWNER, "edible plants", limit=5)

    assert seen["url"].startswith("http://searx.local/search")
    assert "format=json" in seen["url"]
    assert [r.title for r in results] == ["First", "Second"]
    # Snippets arrive untrusted-wrapped (data, not instructions).
    assert "snippet one" in results[0].snippet
    assert "[BEGIN UNTRUSTED CONTENT" in results[0].snippet


async def test_search_non_json_is_degraded():
    svc = await _make_service(lambda req: httpx.Response(200, text="<html>not json</html>"))
    await svc.create_provider(OWNER, name="searx", base_url="http://searx.local")
    with pytest.raises(DegradedCapabilityError):
        await svc.search(OWNER, "q")


async def test_search_unexpected_json_shape_is_degraded():
    # A provider returning a JSON list (not the expected object) degrades cleanly
    # rather than raising AttributeError out of the tool.
    svc = await _make_service(lambda req: httpx.Response(200, json=["not", "an", "object"]))
    await svc.create_provider(OWNER, name="searx", base_url="http://searx.local")
    with pytest.raises(DegradedCapabilityError):
        await svc.search(OWNER, "q")


async def test_search_does_not_follow_redirects():
    # An unguarded redirect on the search path would be an SSRF hole; search refuses
    # to follow and reports the provider as degraded instead.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://169.254.169.254/"})

    svc = await _make_service(handler)
    await svc.create_provider(OWNER, name="searx", base_url="http://searx.local")
    with pytest.raises(DegradedCapabilityError):
        await svc.search(OWNER, "q")


# --- fetch ------------------------------------------------------------------


async def test_fetch_extracts_markdown_and_wraps(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo)
    svc = await _make_service(lambda req: httpx.Response(200, html=_ARTICLE))
    page = await svc.fetch(OWNER, "https://forage.example/guide")

    assert page.title == "Edible Plants" or "Foraging" in (page.title or "")
    assert "Foraging Guide" in page.content  # heading survived → markdown extraction ran
    assert "dandelion" in page.content
    assert "BEGIN UNTRUSTED CONTENT" in page.content
    assert "source=https://forage.example/guide" in page.content


async def test_fetch_refuses_private_target(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo)
    svc = await _make_service(lambda req: httpx.Response(200, html=_ARTICLE))
    with pytest.raises(SSRFError):
        await svc.fetch(OWNER, "http://10.0.0.1/admin")


async def test_fetch_revalidates_ssrf_on_redirect(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo)

    def handler(request: httpx.Request) -> httpx.Response:
        # Public host redirects to a private one — must be caught on the hop.
        return httpx.Response(302, headers={"location": "http://192.168.0.1/secret"})

    svc = await _make_service(handler)
    with pytest.raises(SSRFError):
        await svc.fetch(OWNER, "https://public.example/start")


async def test_fetch_caps_response_size(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo)
    # A tiny byte cap truncates the body to an unparseable fragment → no content.
    svc = await _make_service(lambda req: httpx.Response(200, html=_ARTICLE), max_bytes=10)
    with pytest.raises(WebFetchError):
        await svc.fetch(OWNER, "https://forage.example/guide")


async def test_fetch_http_error_is_web_fetch_error(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo)
    svc = await _make_service(lambda req: httpx.Response(404))
    with pytest.raises(WebFetchError):
        await svc.fetch(OWNER, "https://forage.example/missing")


# --- agent reaches the capability through the toolset stack ----------------


async def test_agent_search_tool_reaches_the_service():
    from pydantic_ai.models.test import TestModel

    from agent import build_chat_orchestrator
    from runs import RunRegistry, RunStatus
    from tools import Capabilities
    from tools.search import web_toolset

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["hit"] = True
        # A populated result exercises SearchResult serialization through Pydantic AI.
        return httpx.Response(
            200, json={"results": [{"title": "Hit", "url": "https://a.example", "content": "c"}]}
        )

    svc = await _make_service(handler)
    await svc.create_provider(OWNER, name="searx", base_url="http://searx.local")
    orch = build_chat_orchestrator(
        "look it up",
        # Tools are namespaced by category → "web_search"; only call search
        # (web_fetch would need a real, resolvable URL).
        model=TestModel(call_tools=["web_search"]),
        categories={"web": web_toolset()},
        capabilities=Capabilities(search=svc),
    )
    run = RunRegistry().submit(kind="chat", owner_id=OWNER, orchestrator=orch)
    await run.wait()

    assert run.status is RunStatus.done
    assert seen.get("hit"), "the search tool should have queried the provider"


async def test_web_tools_degrade_when_capability_absent():
    from pydantic_ai.models.test import TestModel

    from agent import build_chat_orchestrator
    from runs import RunRegistry, RunStatus
    from tools import Capabilities
    from tools.search import web_toolset

    # No search capability wired: both tools must answer "unavailable", not crash.
    orch = build_chat_orchestrator(
        "search and read",
        model=TestModel(call_tools=["web_search", "web_fetch"]),
        categories={"web": web_toolset()},
        capabilities=Capabilities(search=None),
    )
    run = RunRegistry().submit(kind="chat", owner_id=OWNER, orchestrator=orch)
    await run.wait()
    assert run.status is RunStatus.done
