"""The source inventory — the half of claim attribution that makes it retroactive.

A live tool result can be *asked* what it cites; the same result read back out of the
database is the JSON ``core.serde.jsonable`` wrote, and JSON has no methods. So one parser
reads the persisted structure, and these tests pin it against each producer's own
``citations()`` — which is the drift guard the design rests on. A producer that changes
shape must fail here rather than quietly handing the extraction fewer sources than the
turn actually read.
"""

from __future__ import annotations

from core.citations import Citation
from core.serde import jsonable
from core.untrusted import wrap_untrusted
from services.attributions import Claim, SourceRecord, cited_citations, sources_from_results
from services.search import SearchResult, SearchResults
from services.webfetch import FetchedPage
from tools.corpus import CorpusPassage, CorpusPassages


def _keys(results: list) -> list[str]:
    return [record.key for record in sources_from_results(results)]


def test_a_search_batch_reads_back_to_the_keys_its_own_producer_cites():
    batch = SearchResults(
        instruction="",
        results=[
            SearchResult(title="One", url="https://a.example", snippet="alpha"),
            SearchResult(title="Two", url="https://b.example", snippet="beta"),
        ],
    )
    assert _keys([jsonable(batch)]) == [c.key for c in batch.citations()]


def test_a_fetched_page_reads_back_to_the_key_its_own_producer_cites():
    page = FetchedPage(url="https://a.example", title="A page", content="the body")
    assert _keys([jsonable(page)]) == [c.key for c in page.citations()]


def test_a_corpus_batch_reads_back_to_the_keys_its_own_producer_cites():
    batch = CorpusPassages(
        instruction="",
        passages=[
            CorpusPassage(source="notes", ref="a.md", matched_by="dense", text="body"),
            CorpusPassage(source="mail", ref="b.eml", matched_by="sparse", text="other"),
        ],
    )
    assert _keys([jsonable(batch)]) == [c.key for c in batch.citations()]


def test_the_text_is_what_the_model_actually_read():
    """A citation carries a snippet; the extraction needs the body. A page read whole is
    handed whole, a search hit is handed the snippet it was only ever seen through."""
    page = jsonable(FetchedPage(url="https://a.example", title="A", content="the whole body"))
    [record] = sources_from_results([page])
    assert record.text == "the whole body"

    batch = jsonable(
        SearchResults(
            instruction="",
            results=[SearchResult(title="One", url="https://b.example", snippet="just a line")],
        )
    )
    [hit] = sources_from_results([batch])
    assert hit.text == "just a line"


def test_the_untrusted_fence_is_stripped_before_the_reader_sees_it():
    """The markers are how the *model* was handed the text. The second reader gets its
    own fence, minted fresh with its own nonce — carrying the first one through would put
    two nonces in one prompt and hand the fence's own syntax to the text inside it."""
    page = jsonable(
        FetchedPage(
            url="https://a.example", title="A", content=wrap_untrusted("body", source="web")
        )
    )
    [record] = sources_from_results([page])
    assert "UNTRUSTED" not in record.text
    assert record.text == "body"


def test_one_source_met_twice_folds_to_the_stronger_sighting():
    """A page a search listed and a fetch then opened must arrive with the body, not the
    snippet — every claim from past the snippet's end would otherwise read as ungrounded.
    """
    listed = jsonable(
        SearchResults(
            instruction="",
            results=[SearchResult(title="One", url="https://a.example", snippet="a line")],
        )
    )
    read = jsonable(FetchedPage(url="https://a.example", title="One", content="the whole body"))
    [record] = sources_from_results([listed, read])
    assert record.citation.engagement == "read"
    assert record.text == "the whole body"
    # And in the other order — the fold is about the rung, not about arrival time.
    [reversed_record] = sources_from_results([read, listed])
    assert reversed_record.text == "the whole body"


def test_a_result_that_names_no_source_contributes_nothing():
    """Additive, never load-bearing — the same posture the citation stream has."""
    assert sources_from_results(["a degraded capability string", 42, None, {}, []]) == []


def test_a_search_hit_with_no_url_and_a_passage_with_no_ref_are_dropped():
    """The identity *is* the citation for each kind; a row without one is a source the
    operator cannot open, which is the row this feature exists to stop producing."""
    assert sources_from_results([{"results": [{"title": "One", "snippet": "x"}]}]) == []
    assert sources_from_results([{"passages": [{"source": "notes", "text": "x"}]}]) == []


def test_a_batch_is_not_mistaken_for_a_page():
    """A batch is itself a mapping, so the shape tests are ordered — read as a page it
    would be dropped for having no url, and a whole search would vanish."""
    batch = {"instruction": "", "results": [{"url": "https://a.example", "snippet": "x"}],
             "content": "not a page body"}
    assert _keys([batch]) == ["https://a.example"]


def test_cited_is_minted_once_per_source_and_only_for_grounded_claims():
    sources = [
        SourceRecord(citation=Citation(url="https://a.example", title="A"), text="body"),
        SourceRecord(citation=Citation(url="https://b.example", title="B"), text="body"),
    ]
    claims = [
        Claim(claim="one", grounded=True, source_key="https://a.example", passage="p1"),
        Claim(claim="two", grounded=True, source_key="https://a.example", passage="p2"),
        Claim(claim="three", grounded=False, source_key="https://b.example"),
    ]
    cited = cited_citations(claims, sources)
    assert [(c.key, c.engagement, c.snippet) for c in cited] == [
        ("https://a.example", "cited", "p1")
    ]


def test_a_corpus_source_keeps_its_locator_through_the_cited_rung():
    """A corpus citation has no URL, so a consumer must be able to read `kind` and find
    the pair it does have — which means the rung cannot be minted from the key alone."""
    sources = [
        SourceRecord(
            citation=Citation(kind="corpus", source_id="notes", ref="a.md", title="a.md"),
            text="body",
        )
    ]
    [cited] = cited_citations(
        [Claim(claim="one", grounded=True, source_key="notes:a.md", passage="p")], sources
    )
    assert (cited.kind, cited.source_id, cited.ref, cited.url) == ("corpus", "notes", "a.md", None)
