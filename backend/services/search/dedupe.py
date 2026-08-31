"""Run-wide dedupe: a query or URL is dropped before any network call.

A source is not fetched twice within one run, and the same query is not asked twice.
Dedupe is normalized-exact — case/whitespace-folded queries, canonicalized URLs — and
scoped to one run (a fresh :class:`DedupeSets` per run, carried on ``RunDeps``), because
"already read" is a fact about *this* investigation and not a durable one: the page may
well have changed by tomorrow.

The check belongs *before* the network call, so a repeat costs nothing rather than merely
"isn't recorded twice". The seen-set is committed *after* the call succeeds, which is what
:meth:`DedupeSets.peek_query` and :meth:`DedupeSets.peek_url` are for — a search that
failed or a page that refused to render was never actually read, and burning its key would
tell the model it has evidence it does not have.

This began as the deep-research pipeline's own bookkeeping, where one orchestrator owned
the whole gathering loop. Gathering is now something any thread does through the ordinary
web tools, so the discipline moved down beside the capability it constrains.
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
