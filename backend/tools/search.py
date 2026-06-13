"""Web tools — the agent's thin adapter over the web (search + fetch) capability.

Two verbs over :class:`~services.search.SearchService` reached through ``RunDeps``
(no logic here — it lives in the service the REST surface also uses). The results
are typed dataclasses Pydantic AI serializes for the model, already
untrusted-wrapped by the service.

Failure handling leans on the engine: a *recoverable* fetch failure (a blocked or
unreadable URL) raises :class:`ModelRetry`, so Pydantic AI feeds the reason back
and the model tries a different source — bounded by the tool's retry budget. A
*missing* capability (web not wired, or no provider configured) returns a plain
message instead, the same graceful-degradation shape as the memory tools — a retry
can't fix it.
"""

from __future__ import annotations

from pydantic_ai import FunctionToolset, ModelRetry, RunContext

from core.exceptions import DegradedCapabilityError, SSRFError, WebFetchError
from services.search import FetchedPage, SearchResult

from .deps import RunDeps


def search_toolset() -> FunctionToolset[RunDeps]:
    toolset: FunctionToolset[RunDeps] = FunctionToolset()

    @toolset.tool
    async def search(
        ctx: RunContext[RunDeps], query: str, limit: int = 5
    ) -> list[SearchResult] | str:
        """Search the web for a query and return ranked results (title, URL, snippet).

        An empty list means the search ran but found nothing — conclude from that
        rather than retrying the same query."""
        svc = ctx.deps.search
        if svc is None:
            return "Web search is unavailable."
        try:
            return await svc.search(ctx.deps.owner_id, query, limit=limit)
        except DegradedCapabilityError as exc:
            return f"Web search is unavailable: {exc}"

    @toolset.tool(retries=2)
    async def fetch_url(ctx: RunContext[RunDeps], url: str) -> FetchedPage | str:
        """Fetch a single web page and return its main content as Markdown.

        Use after `search` to read a result in full. If a URL can't be fetched you
        will be told why — pick a different source."""
        svc = ctx.deps.search
        if svc is None:
            return "Web fetch is unavailable."
        try:
            return await svc.fetch(ctx.deps.owner_id, url)
        except SSRFError as exc:
            # A refused target is a hard boundary, not a "try again" — tell the model
            # plainly so it moves on instead of probing variants of a blocked address.
            return f"Refused: {exc}"
        except WebFetchError as exc:
            # Recoverable: the page couldn't be read — let the model pick another source.
            raise ModelRetry(str(exc)) from exc

    return toolset
