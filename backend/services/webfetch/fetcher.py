"""BrowserFetcher — fetch one URL by rendering it in a headless browser, then extract
its main content as Markdown.

Replaces the old static httpx+trafilatura fetch: the page is loaded in Chromium so its
JavaScript runs and client-rendered content is present, then the rendered DOM is handed
to the extractor (:mod:`services.webfetch.extract`). Every outbound request is SSRF-guarded
(:mod:`services.webfetch.guard`) and the entry URL is pre-flighted before a browser context
is ever opened. Output is untrusted-wrapped — web content is data, never instructions.

Domain errors only (so the service stays reusable by non-agent callers): ``SSRFError`` for
a refused target (hard boundary), ``WebFetchError`` for an unreadable/unreachable page
(recoverable). The tool layer maps these to a refusal message vs ``ModelRetry``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from core.exceptions import SSRFError, WebFetchError
from core.ssrf import assert_public_url
from core.untrusted import wrap_untrusted

from .browser import ManagedBrowser
from .extract import extract
from .guard import RequestGuard

_INNERTEXT_JS = "() => (document.body ? document.body.innerText : '')"


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
        block_media: bool = True,
        max_bytes: int = 2_000_000,
        min_chars: int = 200,
    ) -> None:
        self._browser = browser
        self._timeout_ms = int(timeout_s * 1000)
        self._wait_until = wait_until
        self._render_wait_ms = render_wait_ms
        self._block_media = block_media
        self._max_bytes = max_bytes
        self._min_chars = min_chars

    async def fetch(self, owner_id: str, url: str) -> FetchedPage:
        """Render ``url`` and return its main content as Markdown. Raises ``SSRFError``
        (refused) or ``WebFetchError`` (unreadable/unreachable/browser unavailable)."""
        # Pre-flight: a refused target never opens a browser context (keeps today's
        # synchronous SSRFError on the entry URL).
        await assert_public_url(url)
        if not self._browser.available:
            raise WebFetchError("web fetch is unavailable (headless browser not running)")
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
        """Load the page in an isolated, SSRF-guarded context and capture the rendered
        HTML, the rendered innerText, and the final URL."""
        guard = RequestGuard(block_media=self._block_media)
        try:
            async with self._browser.context() as ctx:
                await ctx.route("**/*", guard.handle)
                page = await ctx.new_page()
                response = None
                try:
                    response = await page.goto(
                        url, wait_until=self._wait_until, timeout=self._timeout_ms
                    )
                except PlaywrightTimeoutError:
                    pass  # use whatever rendered within the budget
                except PlaywrightError as exc:
                    # A guard-aborted navigation surfaces here as a load error; the
                    # unconditional check below turns it into SSRFError. Other load
                    # failures are recoverable.
                    if guard.blocked_navigation is None:
                        raise WebFetchError(f"could not load {url!r}: {_reason(exc)}") from exc
                # A blocked main-frame navigation is a hard refusal on EVERY path — whether
                # goto raised, returned, or timed out — so the model is told 'refused', not
                # handed a retry for a private host.
                if guard.blocked_navigation is not None:
                    raise SSRFError(
                        f"refused to fetch {url!r}: redirected to non-public "
                        f"{guard.blocked_navigation!r}"
                    )
                if response is not None and response.status >= 400:
                    raise WebFetchError(f"{page.url!r} returned HTTP {response.status}")
                final_url, html, text = await self._snapshot(url, page)
        except (SSRFError, WebFetchError):
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
