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
from services.webfetch import BrowserFetcher, FetchedPage, ManagedBrowser, proxy_script
from services.webfetch.cookies import DomainCookieJar
from services.webfetch.extract import extract
from services.webfetch.fetcher import _looks_like_challenge
from services.webfetch.throttle import DomainThrottle

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


# --- SSRF proxy sidecar (no browser; IP literals resolve offline) ----------


def test_proxy_blocklist_matches_core_ssrf():
    # The sidecar runs with none of our code on its path, so it carries a copy of the SSRF
    # predicate. This guards against the copy drifting from the source of truth.
    import ipaddress

    from core import ssrf as core_ssrf

    samples = [
        "8.8.8.8", "1.1.1.1", "93.184.216.34",          # public
        "127.0.0.1", "10.0.0.1", "192.168.1.1", "172.16.0.1",  # loopback / private
        "169.254.169.254", "100.64.0.1", "224.0.0.1", "0.0.0.0",  # metadata / cgnat / mcast
        "::1", "fe80::1", "2606:4700:4700::1111", "fd00:ec2::254",  # ipv6
    ]
    for s in samples:
        ip = ipaddress.ip_address(s)
        assert proxy_script._is_blocked(ip) == core_ssrf._is_blocked(ip), s


async def _proxy_request(raw: bytes) -> bytes:
    """Run one request through the proxy's dispatcher on loopback; return the first reply line."""
    server = await asyncio.start_server(proxy_script._dispatch, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    task = asyncio.create_task(server.serve_forever())
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(raw)
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=5)
        writer.close()
        return line
    finally:
        server.close()
        task.cancel()


async def test_proxy_refuses_private_connect():
    # A CONNECT to a private host is refused (403) before any tunnel opens — no network.
    line = await _proxy_request(b"CONNECT 10.0.0.1:443 HTTP/1.1\r\nHost: 10.0.0.1\r\n\r\n")
    assert b"403" in line


async def test_proxy_refuses_metadata_http():
    line = await _proxy_request(
        b"GET http://169.254.169.254/latest/meta-data/ HTTP/1.1\r\nHost: x\r\n\r\n"
    )
    assert b"403" in line


async def test_proxy_rejects_malformed_request():
    assert b"400" in await _proxy_request(b"not a real request line\r\n\r\n")


# --- cookie jar: per-domain, TTL'd, bounded (no browser) -------------------


def test_cookie_jar_seeds_by_host_suffix():
    jar = DomainCookieJar(ttl_s=100, max_entries=10)
    jar.store([{"name": "sess", "value": "1", "domain": ".reddit.com", "path": "/"}])
    assert [c["name"] for c in jar.seed_for("https://www.reddit.com/r/x")] == ["sess"]
    assert jar.seed_for("https://example.com/") == []  # different site → nothing


def test_cookie_jar_drops_source_expired_cookie():
    jar = DomainCookieJar(ttl_s=100, max_entries=10)
    jar.store([{"name": "old", "value": "1", "domain": "x.com", "path": "/", "expires": 1.0}])
    assert jar.seed_for("https://x.com/") == []  # already past its own expiry


def test_cookie_jar_later_set_overwrites_and_caps():
    jar = DomainCookieJar(ttl_s=100, max_entries=2)
    jar.store([{"name": "a", "value": "1", "domain": "x.com", "path": "/"}])
    jar.store([{"name": "a", "value": "2", "domain": "x.com", "path": "/"}])  # same key
    jar.store([{"name": "b", "value": "1", "domain": "x.com", "path": "/"}])
    jar.store([{"name": "c", "value": "1", "domain": "x.com", "path": "/"}])  # evicts oldest (a)
    got = {c["name"]: c["value"] for c in jar.seed_for("https://x.com/")}
    assert got == {"b": "1", "c": "1"}


def test_cookie_jar_evicts_on_ttl(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr("services.webfetch.cookies.time.monotonic", lambda: clock["t"])
    jar = DomainCookieJar(ttl_s=10, max_entries=10)
    jar.store([{"name": "s", "value": "1", "domain": "x.com", "path": "/"}])
    clock["t"] += 5
    assert [c["name"] for c in jar.seed_for("https://x.com/")] == ["s"]  # within TTL
    clock["t"] += 10
    assert jar.seed_for("https://x.com/") == []  # past TTL → evicted


# --- per-domain throttle (no browser) --------------------------------------


async def test_throttle_spaces_same_host():
    throttle = DomainThrottle(min_interval_s=0.05)
    start = asyncio.get_event_loop().time()
    async with throttle.slot("https://x.com/a"):
        pass
    async with throttle.slot("https://x.com/b"):
        pass
    assert asyncio.get_event_loop().time() - start >= 0.05  # second waited out the gap


async def test_throttle_does_not_block_distinct_hosts():
    throttle = DomainThrottle(min_interval_s=10.0)
    start = asyncio.get_event_loop().time()
    async with throttle.slot("https://a.com/"):
        pass
    async with throttle.slot("https://b.com/"):  # different host → no wait
        pass
    assert asyncio.get_event_loop().time() - start < 1.0


async def test_throttle_disabled_is_noop():
    async with DomainThrottle(min_interval_s=0.0).slot("https://a.com/"):
        pass  # never waits, never raises


async def test_throttle_prune_keeps_a_locked_host(monkeypatch):
    # At the tracking cap, pruning must skip a host whose lock is held — else two same-host
    # fetches would acquire different locks and run in parallel (the race the throttle prevents).
    monkeypatch.setattr("services.webfetch.throttle._MAX_TRACKED", 1)
    throttle = DomainThrottle(min_interval_s=0.01)
    release = asyncio.Event()

    async def hold_a():
        async with throttle.slot("https://a.com/"):
            await release.wait()

    task = asyncio.create_task(hold_a())
    await asyncio.sleep(0.05)  # let it acquire a.com's slot
    async with throttle.slot("https://b.com/"):  # at cap ⇒ triggers a prune
        pass
    assert "a.com" in throttle._slots  # locked host survived the prune
    release.set()
    await task


# --- challenge-interstitial detection (no browser) -------------------------


def test_detects_challenge_interstitial():
    assert _looks_like_challenge("<title>Just a moment...</title>", "Checking your browser")
    assert _looks_like_challenge("<div class='challenge-platform'></div>", "")


def test_normal_page_is_not_a_challenge():
    assert not _looks_like_challenge("<h1>Guide</h1>", "Real content about foraging dandelions")


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
    async def context(self, url=None):
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
            await browser.apply_stealth(probe)  # client-hint/UA-metadata override
            await probe.goto("data:text/html,<p>ok</p>", wait_until="domcontentloaded")
            assert await probe.evaluate("() => navigator.webdriver") in (False, None)
            user_agent = await probe.evaluate("() => navigator.userAgent")
            assert "HeadlessChrome" not in user_agent and "Chrome/" in user_agent
            assert await probe.evaluate("() => typeof window.chrome") == "object"
            assert await probe.evaluate("() => navigator.languages.length") > 0
            # A fuller window.chrome (app/csi), not the bare { runtime } stub a probe spots.
            assert await probe.evaluate("() => typeof window.chrome.app") == "object"
            assert await probe.evaluate("() => typeof window.chrome.csi") == "function"
            # Named plugin entries — the old [1,2,3,4,5] left plugins[0].name undefined.
            assert await probe.evaluate("() => navigator.plugins.length") == 5
            assert await probe.evaluate("() => navigator.plugins[0].name") == "PDF Viewer"
            # The WebGL renderer agrees with the Linux UA — the old spoof leaked a macOS
            # 'Intel Iris' string under a Linux UA, a cross-check a fingerprinter flags.
            renderer = await probe.evaluate(
                "() => { const c = document.createElement('canvas').getContext('webgl');"
                " return c ? c.getParameter(37446) : ''; }"
            )
            assert "Iris" not in renderer and ("Mesa" in renderer or "ANGLE" in renderer)

        # 3) Client hints agree with the UA (the tell a patched UA string alone misses):
        # the headless shell's 'HeadlessChrome' brand must be gone from navigator.userAgentData
        # and the Sec-CH-UA it derives. userAgentData needs a secure context, which a
        # route-fulfilled https URL provides offline — no network egress.
        async with browser.context() as ctx:
            async def _ok(route):
                await route.fulfill(status=200, content_type="text/html", body="<p>ok</p>")

            await ctx.route("https://stealth.local/**", _ok)
            probe = await ctx.new_page()
            await browser.apply_stealth(probe)
            await probe.goto("https://stealth.local/", wait_until="domcontentloaded")
            assert await probe.evaluate("() => isSecureContext") is True
            brands = await probe.evaluate(
                "() => navigator.userAgentData.brands.map(b => b.brand)"
            )
            assert brands and not any("HeadlessChrome" in b for b in brands)
            assert any("Chrome" in b for b in brands)
            assert await probe.evaluate("() => navigator.userAgentData.platform") == "Linux"
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
