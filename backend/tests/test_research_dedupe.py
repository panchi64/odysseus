"""Run-wide query/URL dedupe (DR-1.4) — normalized-exact, scoped to one run."""

from __future__ import annotations

from research.dedupe import DedupeSets, canonicalize_url, normalize_query


def test_normalize_query_folds_case_and_whitespace():
    assert normalize_query("  Foo   Bar  ") == "foo bar"
    assert normalize_query("foo bar") == "foo bar"


def test_canonicalize_url_folds_scheme_trailing_slash_and_fragment():
    assert canonicalize_url("https://Example.com/Path/") == canonicalize_url(
        "http://example.com/Path#section"
    )
    # A different path is still a different resource.
    assert canonicalize_url("https://example.com/a") != canonicalize_url("https://example.com/b")
    # The query string is kept — it can change what a page serves.
    assert canonicalize_url("https://example.com/a?x=1") != canonicalize_url(
        "https://example.com/a?x=2"
    )


def test_dedupe_sets_mark_seen_once():
    dedupe = DedupeSets()
    assert dedupe.try_query("Odysseus release date") is True
    assert dedupe.try_query("  odysseus   release date ") is False  # same, folded
    assert dedupe.try_query("odysseus pricing") is True

    assert dedupe.try_url("https://example.com/page/") is True
    assert dedupe.try_url("https://example.com/page") is False  # same, sans slash
    assert dedupe.try_url("https://example.com/other") is True


def test_dedupe_sets_drop_blank():
    dedupe = DedupeSets()
    assert dedupe.try_query("   ") is False
    assert dedupe.try_url("") is False


def test_peek_does_not_mark_seen():
    """`peek_query`/`peek_url` let a caller check candidacy without committing —
    the whole point being that an over-cap candidate the caller never acts on stays
    eligible for a later `try_query`/`try_url`."""
    dedupe = DedupeSets()
    assert dedupe.peek_query("odysseus pricing") is True
    assert dedupe.peek_query("odysseus pricing") is True  # still not marked
    assert dedupe.try_query("odysseus pricing") is True  # first real commit succeeds
    assert dedupe.peek_query("odysseus pricing") is False  # now actually seen

    assert dedupe.peek_url("https://example.com/a") is True
    assert dedupe.peek_url("https://example.com/a") is True
    assert dedupe.try_url("https://example.com/a") is True
    assert dedupe.peek_url("https://example.com/a") is False
