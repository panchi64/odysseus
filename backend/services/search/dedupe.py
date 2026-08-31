"""Run-wide dedupe: a query or URL is dropped before any network call.

A source is not fetched twice within one run, and the same search is not run twice.
Dedupe is normalized-exact — case/whitespace-folded queries, canonicalized URLs — and
scoped to one run (a fresh :class:`DedupeSets` per run, carried on ``RunDeps``), because
"already read" is a fact about *this* investigation and not a durable one: the page may
well have changed by tomorrow.

**A search's key is its whole request, not just its words.** ``limit`` and ``time_range``
change which results come back, so two calls that differ only there are two different
reads of the web. Keying on the query alone would refuse the second one and tell the model
its evidence is already above — when what is above answers a different question.

**Claim first, release if the call never happened.** The check has to run before the
network call, so a repeat costs nothing rather than merely "isn't recorded twice"; and
because the call is awaited, a check that did not also *take* the key would let two
concurrent calls in one turn both pass it and both hit the network. So
:meth:`DedupeSets.claim_search` and :meth:`DedupeSets.claim_url` take the key
synchronously and hand it back, and a caller whose call then failed returns it with
:meth:`DedupeSets.release` — a search that errored or a page that refused to render was
never actually read, and keeping its key would tell the model it has evidence it does not
have.

This began as the deep-research pipeline's own bookkeeping, where one orchestrator owned
the whole gathering loop. Gathering is now something any thread does through the ordinary
web tools, so the discipline moved down beside the capability it constrains.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

#: Separates a search key's parts. A unit separator rather than a punctuation character
#: the operator could type, so no query can spell a key that collides with another one's.
_KEY_SEP = "\x1f"


def normalize_query(query: str) -> str:
    """Case/whitespace-folded query key — ``"  Foo   bar"`` and ``"foo bar"`` collide."""
    return " ".join(query.strip().lower().split())


def search_key(query: str, *, limit: int, time_range: str | None) -> str:
    """The key for one search: the folded query plus every argument that changes which
    results it returns. A blank query keys to ``""`` (never a searchable key), so callers
    can treat it like a repeat. See the module docstring on why the arguments are in
    here."""
    folded = normalize_query(query)
    if not folded:
        return ""
    return _KEY_SEP.join((folded, str(limit), time_range or ""))


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
    """Run-wide seen-keys for searches and URLs."""

    seen: set[str] = field(default_factory=set)

    def claim_search(self, query: str, *, limit: int, time_range: str | None) -> str | None:
        """Take the key for this search, returning it the first time and None when it is
        already taken (or the query is blank). Hand the key back to :meth:`release` if the
        search then didn't happen."""
        return self._claim(search_key(query, limit=limit, time_range=time_range))

    def claim_url(self, url: str) -> str | None:
        """Take the key for this URL — :meth:`claim_search` for a page."""
        return self._claim(canonicalize_url(url))

    def release(self, key: str) -> None:
        """Return a claimed key, so the read that never happened can be tried again."""
        self.seen.discard(key)

    def _claim(self, key: str) -> str | None:
        if not key or key in self.seen:
            return None
        self.seen.add(key)
        return key
