"""Web search — querying the open web, and not querying it twice.

:mod:`~services.search.service` is the capability itself: a SearXNG instance (the
backend's own managed one by default) queried for ranked hits, each snippet wrapped as
untrusted content. :mod:`~services.search.dedupe` is the discipline around it — a
normalized-exact seen-set of queries and URLs, scoped to one run, so a thread that reads
widely never spends a round trip re-asking a question it already asked or re-reading a
page it already read.

The two live together because the second is only ever meaningful about the first, and
because the dedupe used to sit inside a research pipeline that owned its own search loop.
Gathering is a thing any thread does now, not a phase of one feature, so the seen-sets
moved down here with it.
"""

from __future__ import annotations

from services.search.dedupe import (
    DedupeSets,
    canonicalize_url,
    normalize_query,
    search_key,
)
from services.search.service import SearchResult, SearchResults, SearchService

__all__ = [
    "DedupeSets",
    "SearchResult",
    "SearchResults",
    "SearchService",
    "canonicalize_url",
    "normalize_query",
    "search_key",
]
