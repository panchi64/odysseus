"""Run-wide dedupe: a query or URL is dropped before any network call.

DR-1.4: a source MUST NOT be fetched more than once within a run, and the same query
MUST NOT be repeated. Dedupe is normalized-exact — case/whitespace-folded queries,
canonicalized URLs — scoped to one run (a fresh :class:`DedupeSets` per run). It is
the caller's job to check ``try_query``/``try_url`` *before* making the search/fetch
call, so a repeat costs nothing, not just "isn't recorded twice".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit


def normalize_query(query: str) -> str:
    """Case/whitespace-folded query key — ``"  Foo   bar"`` and ``"foo bar"`` collide."""
    return " ".join(query.strip().lower().split())


def canonicalize_url(url: str) -> str:
    """A URL key stripped of the parts that don't change what gets fetched: the
    scheme (http/https are the same resource for dedupe purposes), a trailing slash,
    and the fragment. The host is lower-cased; the query string is kept as-is — it can
    change what a page serves, so it stays part of the key. A blank input canonicalizes
    to ``""`` (never a fetchable URL), so callers can treat it like a repeat."""
    url = url.strip()
    if not url:
        return ""
    parts = urlsplit(url)
    netloc = parts.netloc.lower()
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("http", netloc, path, parts.query, ""))


@dataclass
class DedupeSets:
    """Run-wide seen-sets for queries and URLs."""

    seen_queries: set[str] = field(default_factory=set)
    seen_urls: set[str] = field(default_factory=set)

    def try_query(self, query: str) -> bool:
        """Mark ``query`` seen and return True the first time; False (already seen,
        or blank) means: drop it, don't search."""
        key = normalize_query(query)
        if not key or key in self.seen_queries:
            return False
        self.seen_queries.add(key)
        return True

    def try_url(self, url: str) -> bool:
        """Mark ``url`` seen and return True the first time; False means: drop it,
        don't fetch."""
        key = canonicalize_url(url)
        if not key or key in self.seen_urls:
            return False
        self.seen_urls.add(key)
        return True

    def peek_query(self, query: str) -> bool:
        """Would ``try_query`` accept ``query`` right now — without marking it seen.
        Lets a caller cap a batch of candidates to the ones it will *actually* use
        before committing any of them to the seen-set, so a candidate dropped only
        for being over the cap (never searched) stays eligible for a later round —
        see ``try_query``'s own docstring on why marking must track real network
        calls, not just candidacy."""
        key = normalize_query(query)
        return bool(key) and key not in self.seen_queries

    def peek_url(self, url: str) -> bool:
        """Would ``try_url`` accept ``url`` right now — without marking it seen. See
        ``peek_query``."""
        key = canonicalize_url(url)
        return bool(key) and key not in self.seen_urls
