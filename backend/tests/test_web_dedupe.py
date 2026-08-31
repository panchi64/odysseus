"""The web tools refuse a repeat before it costs anything.

A thread that reads widely loops: it re-asks a query it already asked, or re-fetches a
page whose text is already in its own context, and pays a network round trip plus a second
copy of the result for nothing. The run-wide seen-set (`services/search/dedupe.py`, carried
on `RunDeps`) is the discipline salvaged from the deep-research pipeline, now applied where
any thread can benefit from it.

Three properties are the ones that break silently:

- the check runs **before** the call, so a repeat costs no network at all;
- the key is committed only **after** the call succeeded — a search that failed or a page
  that refused to render was never read, and burning its key would tell the model it has
  evidence it does not have;
- ``offset > 0`` is the documented way to continue a truncated page, so a paging fetch is
  never mistaken for a repeat.
"""

from __future__ import annotations

import pytest
from pydantic_ai import ModelRetry

from core.exceptions import DegradedCapabilityError, WebFetchError
from services.search import SearchResults, SearchService
from services.webfetch import BrowserFetcher, FetchedPage
from tools.deps import RunDeps
from tools.search import web_toolset


class _FakeSearch:
    def __init__(self, *, fail: bool = False) -> None:
        self.queries: list[str] = []
        self._fail = fail

    async def search(self, owner_id, query, *, limit=5, time_range=None):
        self.queries.append(query)
        if self._fail:
            raise DegradedCapabilityError("no provider configured")
        return SearchResults(instruction="", results=[])


class _FakeFetcher:
    def __init__(self, *, fail: bool = False) -> None:
        self.urls: list[tuple[str, int]] = []
        self._fail = fail

    async def fetch(self, owner_id, url, *, offset=0, goal=None):
        self.urls.append((url, offset))
        if self._fail:
            raise WebFetchError("the page would not render")
        return FetchedPage(url=url, title="T", content="body")


def _ctx(*, search=None, fetcher=None):
    from core.container import ServiceContainer

    caps = ServiceContainer()
    if search is not None:
        caps.add(search, as_type=SearchService)
    if fetcher is not None:
        caps.add(fetcher, as_type=BrowserFetcher)

    class _Ctx:
        deps = RunDeps(run=None, owner_id="operator", caps=caps)  # type: ignore[arg-type]

    return _Ctx()


async def _call(name: str, ctx, **kwargs):
    return await web_toolset().tools[name].function(ctx, **kwargs)


class TestSearch:
    async def test_the_same_query_is_not_asked_twice(self):
        svc = _FakeSearch()
        ctx = _ctx(search=svc)
        await _call("search", ctx, query="odysseus release date")
        again = await _call("search", ctx, query="  Odysseus   Release Date ")
        # Folded to the same key, so it never reached the provider.
        assert svc.queries == ["odysseus release date"]
        # And the model is told *why* there is nothing — a bare empty result would read
        # as "the web has nothing" and send it looking again.
        assert isinstance(again, str)
        assert "already searched" in again.lower()

    async def test_a_different_query_still_runs(self):
        svc = _FakeSearch()
        ctx = _ctx(search=svc)
        await _call("search", ctx, query="a")
        await _call("search", ctx, query="b")
        assert svc.queries == ["a", "b"]

    async def test_a_failed_search_leaves_the_query_askable(self):
        svc = _FakeSearch(fail=True)
        ctx = _ctx(search=svc)
        first = await _call("search", ctx, query="a")
        assert "unavailable" in first
        # The provider was down, not the answer absent — the same query must still run
        # once it is back.
        await _call("search", ctx, query="a")
        assert svc.queries == ["a", "a"]

    async def test_each_run_starts_with_a_clean_slate(self):
        svc = _FakeSearch()
        await _call("search", _ctx(search=svc), query="a")
        await _call("search", _ctx(search=svc), query="a")
        # "Already read" is a fact about one investigation, not a durable one.
        assert svc.queries == ["a", "a"]


class TestFetch:
    async def test_the_same_page_is_not_fetched_twice(self):
        fetcher = _FakeFetcher()
        ctx = _ctx(fetcher=fetcher)
        await _call("fetch", ctx, url="https://example.com/page/")
        again = await _call("fetch", ctx, url="http://example.com/page#top")
        assert fetcher.urls == [("https://example.com/page/", 0)]
        assert isinstance(again, str)
        assert "already fetched" in again.lower()

    async def test_paging_through_a_long_page_is_not_a_repeat(self):
        fetcher = _FakeFetcher()
        ctx = _ctx(fetcher=fetcher)
        await _call("fetch", ctx, url="https://example.com/a")
        await _call("fetch", ctx, url="https://example.com/a", offset=4000)
        # The tool's own docstring tells the model to do exactly this.
        assert fetcher.urls == [("https://example.com/a", 0), ("https://example.com/a", 4000)]

    async def test_an_unreadable_page_stays_fetchable(self):
        fetcher = _FakeFetcher(fail=True)
        ctx = _ctx(fetcher=fetcher)
        with pytest.raises(ModelRetry):
            await _call("fetch", ctx, url="https://example.com/a")
        with pytest.raises(ModelRetry):
            await _call("fetch", ctx, url="https://example.com/a")
        assert len(fetcher.urls) == 2
