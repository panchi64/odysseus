"""Web fetch: the render-and-extract pipeline.

Four layers, fastest-first:
- ``extract`` — the trafilatura→innerText cascade over an HTML string (no browser).
- ``RequestGuard`` — the per-request SSRF policy (no browser; IP literals stay offline).
- ``BrowserFetcher`` — pre-flight refusal + degrade, and a real Chromium render that
  proves JavaScript-injected content is captured (skipped when Chromium isn't installed).
- the agent reaching ``web_fetch`` through the toolset stack.
"""

from __future__ import annotations

import asyncio
import urllib.parse
from contextlib import asynccontextmanager

import pytest

from core.exceptions import SSRFError, WebFetchError
from services.webfetch import BrowserFetcher, FetchedPage, ManagedBrowser
from services.webfetch.extract import extract
from services.webfetch.guard import RequestGuard

OWNER = "operator"

_ARTICLE = (
    "<html><head><title>Edible Plants</title></head><body><article>"
    "<h1>Foraging Guide</h1>"
    "<p>The dandelion is entirely edible, from root to flower, and grows almost "
    "everywhere people live, which makes it a reliable first plant to learn.</p>"
    "<p>Always positively identify a plant before eating any part of it in the wild.</p>"
    "<table><tr><td>root</td><td>edible</td></tr></table>"
    "</article></body></html>"
)


# --- extract cascade (no browser) ------------------------------------------


def test_extract_article_to_markdown_with_table():
    title, body = extract(_ARTICLE, url="https://forage.example/g", rendered_text="x", min_chars=50)
    assert body is not None
    assert "Foraging Guide" in body  # heading survived → markdown extraction ran
    assert "dandelion" in body
    assert "|" in body  # the table is preserved as Markdown
    assert title == "Edible Plants" or "Foraging" in (title or "")


def test_extract_falls_back_to_innertext_when_thin():
    # A page with no main-content prose: trafilatura finds little, so the rendered
    # innerText carries the result instead.
    thin = "<html><body><nav>home about contact</nav></body></html>"
    fallback = "the actual visible text a reader would see on this page, plainly rendered"
    _title, body = extract(thin, url="https://x.example", rendered_text=fallback, min_chars=500)
    assert body is not None
    assert fallback in body


def test_extract_empty_returns_none():
    _title, body = extract(
        "<html><body></body></html>", url="https://x.example", rendered_text="", min_chars=50
    )
    assert body is None


# --- SSRF request guard (no browser; IP literals resolve offline) ----------


class _FakeFrame:
    def __init__(self, *, main: bool) -> None:
        self.parent_frame = None if main else object()


class _FakeRequest:
    def __init__(self, url: str, *, resource_type: str = "document", main: bool = True) -> None:
        self.url = url
        self.resource_type = resource_type
        self.frame = _FakeFrame(main=main)

    def is_navigation_request(self) -> bool:
        return self.resource_type == "document"


class _FakeRoute:
    def __init__(self, request: _FakeRequest) -> None:
        self.request = request
        self.action: str | None = None

    async def abort(self) -> None:
        self.action = "abort"

    async def continue_(self) -> None:
        self.action = "continue"


async def test_guard_blocks_private_navigation_and_records_it():
    route = _FakeRoute(_FakeRequest("http://10.0.0.1/admin"))
    guard = RequestGuard(block_media=True)
    await guard.handle(route)  # type: ignore[arg-type]
    assert route.action == "abort"
    assert guard.blocked_navigation == "http://10.0.0.1/admin"


async def test_guard_allows_public_request():
    route = _FakeRoute(_FakeRequest("http://93.184.216.34/page"))
    guard = RequestGuard(block_media=True)
    await guard.handle(route)  # type: ignore[arg-type]
    assert route.action == "continue"
    assert guard.blocked_navigation is None


async def test_guard_blocks_media_when_enabled():
    route = _FakeRoute(_FakeRequest("http://93.184.216.34/banner.png", resource_type="image"))
    guard = RequestGuard(block_media=True)
    await guard.handle(route)  # type: ignore[arg-type]
    assert route.action == "abort"


async def test_guard_allows_inert_scheme():
    route = _FakeRoute(_FakeRequest("data:text/html,<p>hi</p>"))
    guard = RequestGuard(block_media=True)
    await guard.handle(route)  # type: ignore[arg-type]
    assert route.action == "continue"


class _DetachedFrameRequest:
    """A request whose frame access raises — models a frame detached mid-flight."""

    url = "http://10.0.0.1/admin"
    resource_type = "document"

    def is_navigation_request(self) -> bool:
        return True

    @property
    def frame(self):
        raise RuntimeError("frame detached")


async def test_guard_survives_detached_frame_on_blocked_nav():
    # A private target whose frame access raises must still resolve the route (abort), not
    # throw out of the handler and leave the request hanging until the timeout budget.
    route = _FakeRoute(_DetachedFrameRequest())  # type: ignore[arg-type]
    guard = RequestGuard(block_media=True)
    await guard.handle(route)  # type: ignore[arg-type]
    assert route.action == "abort"
    assert guard.blocked_navigation is None  # detection failed safe; the route still aborted


# --- BrowserFetcher: pre-flight + degrade (no browser) ---------------------


async def test_fetch_refuses_private_target_before_opening_browser():
    # enabled=False ⇒ never started; the pre-flight SSRF check must fire first anyway.
    fetcher = BrowserFetcher(
        browser=ManagedBrowser(
            enabled=False,
            image="x",
            startup_timeout_s=1.0,
            concurrency=1,
            user_agent="t",
            locale="en-US",
            timezone_id="UTC",
        )
    )
    with pytest.raises(SSRFError):
        await fetcher.fetch(OWNER, "http://10.0.0.1/admin")


async def test_fetch_degrades_when_browser_unavailable():
    fetcher = BrowserFetcher(
        browser=ManagedBrowser(
            enabled=False,
            image="x",
            startup_timeout_s=1.0,
            concurrency=1,
            user_agent="t",
            locale="en-US",
            timezone_id="UTC",
        )
    )
    # A public IP literal passes the pre-flight offline; the unavailable browser then degrades.
    with pytest.raises(WebFetchError):
        await fetcher.fetch(OWNER, "http://93.184.216.34/")


class _DroppingBrowser:
    """available reports True, but acquiring a context fails — models the browser dropping
    between the availability check and context entry (a TOCTOU disconnect)."""

    available = True

    @asynccontextmanager
    async def context(self):
        raise RuntimeError("browser is not available")
        yield  # pragma: no cover - unreachable


async def test_fetch_maps_browser_dropout_to_webfetch_error():
    # Public IP literal passes the pre-flight and the available-check; context() then raises
    # RuntimeError. It must surface as a recoverable WebFetchError, not an unhandled error
    # the tool can't translate.
    fetcher = BrowserFetcher(browser=_DroppingBrowser())  # type: ignore[arg-type]
    with pytest.raises(WebFetchError):
        await fetcher.fetch(OWNER, "http://93.184.216.34/")


# --- containerized browser: a real render (skipped without a runtime/image) ------


async def _browser_or_skip() -> ManagedBrowser:
    browser = ManagedBrowser(
        enabled=True,
        image="chromedp/headless-shell:latest",
        startup_timeout_s=45.0,
        concurrency=2,
        user_agent="",
        locale="en-US",
        timezone_id="America/New_York",
    )
    await browser.start()
    for _ in range(240):  # bring-up runs in the background; wait up to ~60s for the container
        if browser.available:
            break
        await asyncio.sleep(0.25)
    if not browser.available:
        await browser.stop()
        pytest.skip("web fetch container unavailable (no container runtime or image)")
    return browser


async def _allow_all(url: str) -> None:
    return None


async def test_containerized_browser_renders_js_extracts_and_is_stealthed(monkeypatch):
    browser = await _browser_or_skip()
    try:
        # 1) The fetch pipeline renders a JS-built page and extracts its content as Markdown.
        # Let the synthetic data: URL past the entry pre-flight (the guard treats data: as
        # inert, so no real SSRF policy is bypassed for network egress).
        monkeypatch.setattr("services.webfetch.fetcher.assert_public_url", _allow_all)
        fetcher = BrowserFetcher(browser=browser, min_chars=50, render_wait_ms=100)
        page_html = (
            "<html><head><title>Dyn</title></head><body><div id='r'></div>"
            "<script>document.getElementById('r').innerHTML="
            "'<article><h1>Dynamic Heading</h1><p>'"
            "+'real rendered content here. '.repeat(20)+'</p></article>'</script>"
            "</body></html>"
        )
        page = await fetcher.fetch(OWNER, "data:text/html," + urllib.parse.quote(page_html))
        # The content only exists after the script runs — proves we render, not just GET.
        assert "Dynamic Heading" in page.content
        assert "real rendered content here" in page.content
        assert "BEGIN UNTRUSTED CONTENT" in page.content

        # 2) The browser presents as a normal user's Chrome, not an automated headless one.
        async with browser.context() as ctx:
            probe = await ctx.new_page()
            await probe.goto("data:text/html,<p>ok</p>", wait_until="domcontentloaded")
            assert await probe.evaluate("() => navigator.webdriver") in (False, None)
            user_agent = await probe.evaluate("() => navigator.userAgent")
            assert "HeadlessChrome" not in user_agent and "Chrome/" in user_agent
            assert await probe.evaluate("() => typeof window.chrome") == "object"
            assert await probe.evaluate("() => navigator.languages.length") > 0
    finally:
        await browser.stop()


# --- agent reaches the fetch tool through the toolset stack ----------------


async def test_web_fetch_tool_reaches_the_fetcher():
    from pydantic_ai.models.test import TestModel

    from agent import build_chat_orchestrator
    from runs import RunRegistry, RunStatus
    from tools import Capabilities
    from tools.search import web_toolset

    seen: dict[str, str] = {}

    class _StubFetcher:
        async def fetch(self, owner_id: str, url: str) -> FetchedPage:
            seen["url"] = url
            return FetchedPage(url=url, title="t", content="body")

    orch = build_chat_orchestrator(
        "read it",
        model=TestModel(call_tools=["web_fetch"]),
        categories={"web": web_toolset()},
        capabilities=Capabilities(fetcher=_StubFetcher()),
    )
    run = RunRegistry().submit(kind="chat", owner_id=OWNER, orchestrator=orch)
    await run.wait()

    assert run.status is RunStatus.done
    assert "url" in seen, "the fetch tool should have reached the fetcher capability"
