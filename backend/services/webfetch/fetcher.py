"""BrowserFetcher — fetch one URL by rendering it in a headless browser, then extract
its main content as Markdown.

Replaces the old static httpx+trafilatura fetch: the page is loaded in Chromium so its
JavaScript runs and client-rendered content is present, then the rendered DOM is handed
to the extractor (:mod:`services.webfetch.extract`). The entry URL is pre-flighted
(:func:`core.ssrf.assert_public_url`) before a context opens, and every request the browser
then makes is gated by the proxy sidecar (:mod:`services.webfetch.proxy_script`). Output is
untrusted-wrapped — web content is data, never instructions.

Domain errors only (so the service stays reusable by non-agent callers): ``SSRFError`` for
a target refused by the pre-flight (hard boundary), ``WebFetchError`` for an
unreadable/unreachable page or a request the proxy refused mid-navigation (recoverable). The
tool layer maps these to a refusal message vs ``ModelRetry``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from core.exceptions import WebFetchError
from core.ssrf import assert_public_url
from core.untrusted import wrap_untrusted

from .browser import ManagedBrowser
from .extract import extract
from .throttle import DomainThrottle

_INNERTEXT_JS = "() => (document.body ? document.body.innerText : '')"

# An interstitial a bot wall serves while it runs its JS check (Cloudflare/DataDome/Reddit
# class). We can't *solve* a hostile challenge, but a real browser often clears a soft one
# on its own within a few seconds — so when the first render looks like one of these, we
# wait for it to settle and re-snapshot rather than returning the interstitial as content.
_CHALLENGE_MARKERS = (
    "just a moment",
    "checking your browser",
    "verify you are human",
    "verifying you are human",
    "attention required",
    "enable javascript and cookies to continue",
    "needs to review the security of your connection",
    "challenge-platform",
    "cf-chl",
)


# A bot wall often parks the browser on a challenge URL while its JS runs (Reddit appends
# ?js_challenge=1; Cloudflare uses /cdn-cgi/challenge + __cf_chl params). The challenge page
# itself can be near-empty, so the URL is the more reliable tell than its body text.
_CHALLENGE_URL_MARKERS = ("js_challenge=", "__cf_chl", "cf_chl_", "/cdn-cgi/challenge")


def _looks_like_challenge(html: str, text: str) -> bool:
    """Whether a rendered page reads as a bot-wall interstitial rather than real content."""
    blob = (text or "")[:2000].lower()
    markup = (html or "")[:6000].lower()
    return any(m in blob or m in markup for m in _CHALLENGE_MARKERS)


def _is_challenge_url(url: str) -> bool:
    """Whether a URL is a bot wall's challenge endpoint (the browser was parked on it)."""
    low = (url or "").lower()
    return any(m in low for m in _CHALLENGE_URL_MARKERS)


@dataclass(frozen=True)
class FetchedPage:
    """A fetched page's main content as Markdown, untrusted-wrapped."""

    url: str
    title: str | None
    content: str


class BrowserFetcher:
    """Render-and-extract a single URL. The bounds default to the configured settings and
    are injected so tests can shrink them."""

    def __init__(
        self,
        *,
        browser: ManagedBrowser,
        timeout_s: float = 15.0,
        wait_until: str = "domcontentloaded",
        render_wait_ms: int = 250,
        max_bytes: int = 2_000_000,
        min_chars: int = 200,
        min_interval_s: float = 0.0,
        challenge_waits: int = 0,
        challenge_wait_ms: int = 5000,
    ) -> None:
        self._browser = browser
        self._timeout_ms = int(timeout_s * 1000)
        self._wait_until = wait_until
        self._render_wait_ms = render_wait_ms
        self._max_bytes = max_bytes
        self._min_chars = min_chars
        self._throttle = DomainThrottle(min_interval_s=min_interval_s)
        self._challenge_waits = challenge_waits
        self._challenge_wait_ms = challenge_wait_ms

    async def fetch(self, owner_id: str, url: str) -> FetchedPage:
        """Render ``url`` and return its main content as Markdown. Raises ``SSRFError``
        (refused) or ``WebFetchError`` (unreadable/unreachable/browser unavailable)."""
        # Pre-flight: a refused target never opens a browser context (keeps today's
        # synchronous SSRFError on the entry URL).
        await assert_public_url(url)
        if not self._browser.available:
            raise WebFetchError("web fetch is unavailable (headless browser not running)")
        # Per-host politeness: serialize same-site fetches with a minimum gap between them.
        async with self._throttle.slot(url):
            html, text, final_url = await self._render(url)
        title, body = await asyncio.to_thread(
            extract, html, url=final_url, rendered_text=text, min_chars=self._min_chars
        )
        if not body:
            raise WebFetchError(f"no readable content at {final_url!r}")
        return FetchedPage(
            url=final_url, title=title, content=wrap_untrusted(body, source=final_url)
        )

    async def _render(self, url: str) -> tuple[str, str, str]:
        """Load the page in an isolated context and capture the rendered HTML, the rendered
        innerText, and the final URL. SSRF is enforced out-of-browser by the proxy sidecar
        (it refuses non-public destinations on every request, including redirects); a request
        it refuses surfaces here as a load failure, which degrades to a recoverable error —
        the synchronous pre-flight in :meth:`fetch` is what yields the hard SSRF refusal."""
        try:
            # Pass the URL so the site's cached cookies (a prior challenge's clearance) seed
            # this context and any it gains are harvested back when it closes.
            async with self._browser.context(url) as ctx:
                page = await ctx.new_page()
                await self._browser.apply_stealth(page)  # client hints, before any nav
                response = None
                try:
                    response = await page.goto(
                        url, wait_until=self._wait_until, timeout=self._timeout_ms
                    )
                except PlaywrightTimeoutError:
                    pass  # use whatever rendered within the budget
                except PlaywrightError as exc:
                    raise WebFetchError(f"could not load {url!r}: {_reason(exc)}") from exc
                if response is not None and response.status >= 400:
                    raise WebFetchError(f"{page.url!r} returned HTTP {response.status}")
                final_url, html, text = await self._capture(url, page)
        except WebFetchError:
            raise
        except RuntimeError as exc:
            # The browser dropped between fetch()'s availability check and acquiring a
            # context — degrade rather than leak an unhandled error to the tool.
            raise WebFetchError(f"web fetch is unavailable: {exc}") from exc
        except PlaywrightError as exc:
            raise WebFetchError(f"could not render {url!r}: {_reason(exc)}") from exc
        # Cap (in characters) what we hand the extractor. The browser already buffered the
        # full page (the container's --memory bounds that); this just keeps an outsized DOM
        # from ballooning the extractor's input. trafilatura/lxml recover from a mid-tag cut.
        return html[: self._max_bytes], (text or "")[: self._max_bytes], final_url

    async def _capture(self, url: str, page) -> tuple[str, str, str]:
        """Snapshot the page, and if it reads as a bot-wall interstitial, wait for it to
        clear and re-snapshot — up to ``challenge_waits`` times. A real browser often
        settles a soft challenge on its own within a few seconds; this stops us returning
        the 'Just a moment…' page as if it were the content (it can't beat a hard wall)."""
        final_url, html, text = await self._snapshot(url, page)
        for _ in range(self._challenge_waits):
            # A challenge URL alone isn't enough to keep waiting — some walls keep their
            # param in the URL after the real content loads; only wait while content is thin.
            thin = len((text or "").strip()) < self._min_chars
            if not (_looks_like_challenge(html, text) or (_is_challenge_url(final_url) and thin)):
                break
            try:
                await page.wait_for_timeout(self._challenge_wait_ms)
            except PlaywrightError:
                break  # page/context went away mid-wait — return what we have
            try:
                final_url, html, text = await self._snapshot(url, page)
            except WebFetchError:
                break  # a re-snapshot that won't settle ⇒ keep the prior best-effort capture
        return final_url, html, text

    async def _snapshot(self, url: str, page) -> tuple[str, str, str]:
        """Settle, then snapshot the final URL + rendered HTML + innerText — bounded by the
        timeout so a page whose JS never quiesces can't hold the fetch open indefinitely
        (content()/evaluate() don't honour the navigation timeout)."""

        async def take() -> tuple[str, str, str]:
            if self._render_wait_ms:
                await page.wait_for_timeout(self._render_wait_ms)
            html = await page.content()
            text = await page.evaluate(_INNERTEXT_JS)
            return page.url, html, text

        try:
            return await asyncio.wait_for(take(), timeout=self._timeout_ms / 1000)
        except TimeoutError as exc:
            raise WebFetchError(f"render did not settle for {url!r}") from exc


def _reason(exc: Exception) -> str:
    """Playwright errors are multi-line and verbose — take the first line for the model."""
    first = str(exc).splitlines()
    return first[0] if first else exc.__class__.__name__
