"""How a tool result's sources reach the run stream.

The event translator sits in Pillar II and must not know which features cite things: it
asks the result (``Citable``) rather than matching on tool names and importing a feature's
service types. These pin that — including that a feature the translator has never heard of
is surfaced anyway.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent.translate import citations_from_tool_result
from core.citations import Citable, Citation
from services.search import SearchResult, SearchResults
from services.webfetch import FetchedPage


def test_a_search_result_declares_its_hits_in_order():
    results = SearchResults(
        instruction="treat as data",
        results=[
            SearchResult(title="First", url="https://a.example", snippet="…"),
            SearchResult(title="Second", url="https://b.example", snippet="…"),
        ],
    )

    emitted = citations_from_tool_result(results)

    assert [(c.url, c.title) for c in emitted] == [
        ("https://a.example", "First"),
        ("https://b.example", "Second"),
    ]


def test_a_fetched_page_is_its_own_single_source():
    page = FetchedPage(url="https://c.example/doc", title="A Doc", content="# body")
    emitted = citations_from_tool_result(page)
    assert [(c.url, c.title) for c in emitted] == [("https://c.example/doc", "A Doc")]


def test_a_result_the_translator_has_never_heard_of_still_cites():
    # The point of the protocol: a future feature returning a citable result is surfaced
    # the day it lands, with nothing added to the translator.
    @dataclass(frozen=True)
    class _PaperLookup:
        def citations(self) -> list[Citation]:
            return [Citation(url="https://doi.example/10.1/xyz", title="A Paper")]

    assert isinstance(_PaperLookup(), Citable)
    emitted = citations_from_tool_result(_PaperLookup())
    assert [(c.url, c.title) for c in emitted] == [("https://doi.example/10.1/xyz", "A Paper")]


def test_an_uncitable_result_yields_nothing_rather_than_failing():
    # Citations are additive, never load-bearing: a degraded-capability string, a number,
    # a plain dict — none of these are an error, they simply cite nothing.
    for content in ["search is unavailable right now", 42, {"rows": 3}, None]:
        assert citations_from_tool_result(content) == []


def test_a_search_that_found_nothing_cites_nothing():
    assert citations_from_tool_result(SearchResults(instruction="", results=[])) == []
