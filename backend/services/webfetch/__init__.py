"""Web page fetching — render in a headless browser, extract to Markdown.

The open web is treated as always-dynamic: a page is loaded in real Chromium (so its
JavaScript runs) and the rendered DOM is extracted to Markdown. Public surface:

- :class:`ManagedBrowser` — the headless Chromium lifecycle (started/stopped by the app).
- :class:`BrowserFetcher` — the capability: ``fetch(owner_id, url) -> FetchedPage``.
- :class:`FetchedPage` — a fetched page's untrusted-wrapped Markdown content.
"""

from __future__ import annotations

from .browser import ManagedBrowser
from .fetcher import BrowserFetcher, FetchedPage

__all__ = ["BrowserFetcher", "FetchedPage", "ManagedBrowser"]
