"""Web tools — the agent's thin adapters over the web capabilities.

Two verbs reached through ``RunDeps``: ``search`` over
:class:`~services.search.SearchService` (SearXNG) and ``fetch`` over
:class:`~services.webfetch.BrowserFetcher` (render the page in a headless browser, extract
to Markdown). No logic here — it lives in the services. The results are typed dataclasses
Pydantic AI serializes for the model, already untrusted-wrapped by the service.

Failure handling leans on the engine: a *recoverable* fetch failure (a blocked or
unreadable URL) raises :class:`ModelRetry`, so Pydantic AI feeds the reason back
and the model tries a different source — bounded by the tool's retry budget. A
*missing* capability (web not wired, or no provider configured) returns a plain
message instead, the same graceful-degradation shape as the memory tools — a retry
can't fix it.
"""

from __future__ import annotations

from typing import Literal

from pydantic_ai import FunctionToolset, ModelRetry, RunContext

from core.exceptions import DegradedCapabilityError, SSRFError, WebFetchError
from services.search import SearchResults, SearchService
from services.webfetch import BrowserFetcher, FetchedPage

from .deps import RunDeps


def web_toolset() -> FunctionToolset[RunDeps]:
    toolset: FunctionToolset[RunDeps] = FunctionToolset()

    @toolset.tool
    async def search(
        ctx: RunContext[RunDeps],
        query: str,
        limit: int = 5,
        time_range: Literal["day", "week", "month", "year"] | None = None,
    ) -> SearchResults | str:
        """Search the web for a query and return ranked results (title, URL, snippet).

        Use `time_range` to restrict results to recent pages when the question is
        time-sensitive; `published` on a result is its publication date when the engine
        knew it. No results means the search ran but found nothing — conclude from
        that rather than retrying the same query."""
        svc = ctx.deps.caps.get_optional(SearchService)
        if svc is None:
            return "Web search is unavailable."
        try:
            return await svc.search(ctx.deps.owner_id, query, limit=limit, time_range=time_range)
        except DegradedCapabilityError as exc:
            return f"Web search is unavailable: {exc}"

    @toolset.tool(retries=2)
    async def fetch(
        ctx: RunContext[RunDeps], url: str, offset: int = 0, goal: str | None = None
    ) -> FetchedPage | str:
        """Fetch a single web page and return its main content as Markdown.

        Use after `search` to read a result in full. State the information you are looking
        for in `goal` — on large pages the result is then distilled to what's relevant to
        it; omit `goal` (or pass `offset`) to read the raw text. Fetching returns up to a
        fixed token budget of the page; when the result ends with a truncation notice, call
        `fetch` again with the same `url` and the `offset` the notice gives to continue
        reading (dynamic pages may shift slightly between calls). If a URL can't be
        fetched you will be told why — pick a different source."""
        svc = ctx.deps.caps.get_optional(BrowserFetcher)
        if svc is None:
            return "Web fetch is unavailable."
        try:
            return await svc.fetch(ctx.deps.owner_id, url, offset=offset, goal=goal)
        except SSRFError as exc:
            # A refused target is a hard boundary, not a "try again" — tell the model
            # plainly so it moves on instead of probing variants of a blocked address.
            return f"Refused: {exc}"
        except WebFetchError as exc:
            # Recoverable: the page couldn't be read — let the model pick another source.
            raise ModelRetry(str(exc)) from exc

    return toolset
