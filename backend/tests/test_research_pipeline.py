"""The research pipeline core: the rounds loop, its dynamic fan-out, and its bounds —
driven by fake search/fetch services and `FunctionModel` stand-ins for the main/
utility roles (branched on `info.instructions`, since every structured-output call
surfaces the same `final_result` tool name)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel

from core.exceptions import DegradedCapabilityError, WebFetchError
from research import (
    ResearchDeps,
    ResearchPlan,
    SearchUnavailableError,
    agents,
    run_research,
)
from services.search import SearchResult, SearchResults
from services.webfetch import FetchedPage


# --- fakes --------------------------------------------------------------------
@dataclass
class FakeSearch:
    hits: dict[str, list[SearchResult]] = field(default_factory=dict)
    raise_for: frozenset[str] = frozenset()
    calls: list[str] = field(default_factory=list)

    async def search(self, owner_id, query, *, limit=None, time_range=None):
        self.calls.append(query)
        if query in self.raise_for:
            raise DegradedCapabilityError("search down")
        return SearchResults(instruction="", results=list(self.hits.get(query, [])))


@dataclass
class FakeFetcher:
    pages: dict[str, FetchedPage] = field(default_factory=dict)
    fail: frozenset[str] = frozenset()
    calls: list[str] = field(default_factory=list)

    async def fetch(self, owner_id, url, *, offset=0, goal=None):
        self.calls.append(url)
        if url in self.fail:
            raise WebFetchError("fetch failed")
        return self.pages[url]


def _last_user_text(messages) -> str:
    request = messages[-1]
    assert isinstance(request, ModelRequest)
    for part in request.parts:
        if isinstance(part, UserPromptPart):
            return part.content if isinstance(part.content, str) else str(part.content)
    return ""


def _tool_response(info, **args) -> ModelResponse:
    tool = info.output_tools[0]
    return ModelResponse(parts=[ToolCallPart(tool_name=tool.name, args=args)])


class MainModelFake:
    """Stands in for the main model across select_queries/refine_answer/write_report —
    the three main-model calls, told apart by their (fixed) instructions text."""

    def __init__(self, *, queries_by_round=None, refine_by_round=None, report="REPORT"):
        self.queries_by_round = queries_by_round or []
        self.refine_by_round = refine_by_round or []
        self.report = report
        self.query_calls = 0
        self.refine_calls = 0
        self.report_calls = 0
        self.captured_report_prompt: str | None = None

    async def __call__(self, messages, info) -> ModelResponse:
        if info.instructions == agents._QUERY_INSTRUCTIONS:
            idx = min(self.query_calls, len(self.queries_by_round) - 1)
            queries = self.queries_by_round[idx]
            self.query_calls += 1
            return _tool_response(info, queries=queries)
        if info.instructions == agents._REFINE_INSTRUCTIONS:
            idx = min(self.refine_calls, len(self.refine_by_round) - 1)
            answer, gaps = self.refine_by_round[idx]
            self.refine_calls += 1
            return _tool_response(info, answer=answer, gaps=gaps)
        # write_report: str output, no output tool — a plain text response.
        self.report_calls += 1
        self.captured_report_prompt = _last_user_text(messages)
        return ModelResponse(parts=[TextPart(content=self.report)])


class UtilityModelFake:
    """Stands in for the utility model across extract_evidence/judge_comprehensive."""

    def __init__(self, *, claim_by_call=None, comprehensive_by_call=None):
        self.claim_by_call = claim_by_call or []
        self.comprehensive_by_call = comprehensive_by_call or []
        self.extract_calls = 0
        self.judge_calls = 0

    async def __call__(self, messages, info) -> ModelResponse:
        if info.instructions == agents._EXTRACT_INSTRUCTIONS:
            idx = min(self.extract_calls, len(self.claim_by_call) - 1) if self.claim_by_call else 0
            claim = self.claim_by_call[idx] if self.claim_by_call else "a claim"
            self.extract_calls += 1
            return _tool_response(info, claims=[{"claim": claim}] if claim else [])
        # judge_comprehensive
        idx = min(self.judge_calls, len(self.comprehensive_by_call) - 1)
        comprehensive = self.comprehensive_by_call[idx]
        self.judge_calls += 1
        return _tool_response(info, comprehensive=comprehensive, reason="because")


def _deps(*, main_fake, utility_fake, search=None, fetcher=None, **overrides) -> ResearchDeps:
    defaults = dict(
        owner_id="operator",
        # `FunctionModel` only recognizes a coroutine *function* (`inspect.
        # iscoroutinefunction`), not a callable instance with an async `__call__` — so
        # it's handed the bound method, which passes that check.
        main_model=FunctionModel(main_fake.__call__),
        utility_model=FunctionModel(utility_fake.__call__),
        main_settings={},
        utility_settings={},
        search=search or FakeSearch(),
        fetcher=fetcher or FakeFetcher(),
        max_rounds=4,
        time_limit_s=900.0,
        round_floor=2,
        max_concurrency=4,
        empty_rounds_abort=2,
    )
    defaults.update(overrides)
    return ResearchDeps(**defaults)


_PLAN = ResearchPlan(objective="Find out about X", angles=["angle one"])


# --- dedupe drops repeats before any network call -----------------------------
async def test_dedupe_drops_repeated_query_and_url_pre_network():
    hit = SearchResult(title="A", url="https://example.com/a", snippet="s")
    search = FakeSearch(hits={"the query": [hit]})
    fetcher = FakeFetcher(
        pages={
            "https://example.com/a": FetchedPage(
                url="https://example.com/a", title="A", content="content"
            )
        }
    )
    main = MainModelFake(
        # Round 1 and round 2 both propose the *same* query — the second occurrence
        # must never reach the search service.
        queries_by_round=[["the query"], ["the query"]],
        refine_by_round=[("partial", ["gap"]), ("final", [])],
    )
    utility = UtilityModelFake(claim_by_call=["claim"])
    deps = _deps(
        main_fake=main, utility_fake=utility, search=search, fetcher=fetcher, round_floor=5
    )

    events = []
    result = await run_research(_PLAN, "the question", deps, events.append)

    assert search.calls == ["the query"]  # round 2's repeat never called search
    assert fetcher.calls == ["https://example.com/a"]  # never re-fetched either
    assert result.sources == 1
    assert result.queries == 1


async def test_query_fanout_is_capped_by_max_concurrency():
    search = FakeSearch()
    main = MainModelFake(
        queries_by_round=[["q1", "q2", "q3"]],
        refine_by_round=[("done", [])],  # gaps empty ⇒ stop after round 1
    )
    utility = UtilityModelFake()
    deps = _deps(main_fake=main, utility_fake=utility, search=search, max_concurrency=2)

    await run_research(_PLAN, "q", deps, lambda body: None)

    assert len(search.calls) == 2  # 3 queries proposed, capped to 2


async def test_over_cap_query_remains_eligible_for_a_later_round():
    """A query that loses the round-1 fan-out cap must NOT be treated as already
    searched — it stays eligible so a later round can still search it (regression for
    the cap-then-mark ordering: capping must happen before dedupe marks anything
    seen, not after)."""
    search = FakeSearch()
    main = MainModelFake(
        # Round 1 proposes 3 queries but the cap is 2 — "q3" loses the cap. Round 2
        # re-proposes just "q3" (the gap it covers is still open).
        queries_by_round=[["q1", "q2", "q3"], ["q3"]],
        refine_by_round=[("partial", ["gap"]), ("final", [])],
    )
    utility = UtilityModelFake()
    # round_floor above the number of rounds this run takes, so the judge (which this
    # test doesn't fake outputs for) is never consulted — "not gaps" ends the loop.
    deps = _deps(
        main_fake=main,
        utility_fake=utility,
        search=search,
        max_concurrency=2,
        round_floor=5,
        empty_rounds_abort=5,  # zero-hit rounds are fine here — only query routing is under test
    )

    result = await run_research(_PLAN, "q", deps, lambda body: None)

    # "q3" was dropped from round 1's batch by the cap, then actually searched in
    # round 2 — it must appear exactly once, not be silently blacklisted.
    assert search.calls == ["q1", "q2", "q3"]
    assert result.queries == 3  # not inflated by a query that was capped, never searched


# --- early-stop honors the round floor -----------------------------------------
async def test_judge_is_not_consulted_before_the_round_floor():
    hit = SearchResult(title="A", url="https://example.com/a", snippet="s")
    search = FakeSearch(hits={"q1": [hit], "q2": [hit]})
    fetcher = FakeFetcher(
        pages={
            "https://example.com/a": FetchedPage(
                url="https://example.com/a", title="A", content="c"
            )
        }
    )
    main = MainModelFake(
        queries_by_round=[["q1"], ["q2"], ["q3"]],
        # Gaps stay open every round, so only the judge (or max_rounds) can stop it.
        refine_by_round=[("a1", ["gap"]), ("a2", ["gap"]), ("a3", [])],
    )
    utility = UtilityModelFake(
        claim_by_call=["c1", "c2"],
        comprehensive_by_call=[True],  # would stop immediately if consulted round 1
    )
    deps = _deps(
        main_fake=main, utility_fake=utility, search=search, fetcher=fetcher, round_floor=2
    )

    result = await run_research(_PLAN, "q", deps, lambda body: None)

    assert utility.judge_calls == 1  # never asked in round 1 (below the floor)
    assert result.rounds == 2  # stopped exactly at the floor once the judge said yes


# --- empty-rounds abort ---------------------------------------------------------
async def test_two_empty_rounds_abort_with_a_clear_message():
    search = FakeSearch()  # every query returns zero hits
    main = MainModelFake(
        queries_by_round=[["q-round-1"], ["q-round-2"]],
        refine_by_round=[("still nothing", ["gap"])],
    )
    utility = UtilityModelFake()
    deps = _deps(
        main_fake=main,
        utility_fake=utility,
        search=search,
        round_floor=5,
        empty_rounds_abort=2,
    )

    events = []
    with pytest.raises(SearchUnavailableError) as exc_info:
        await run_research(_PLAN, "q", deps, events.append)

    assert "unavailable" in str(exc_info.value)
    assert search.calls == ["q-round-1", "q-round-2"]  # aborted right after round 2's search
    notices = [e for e in events if getattr(e, "type", None) == "limit.notice"]
    assert len(notices) == 1
    assert notices[0].limit == "search"
    assert notices[0].message == str(exc_info.value)


# --- time-limit stop -------------------------------------------------------------
async def test_zero_time_limit_skips_every_round_and_still_writes():
    search = FakeSearch()
    main = MainModelFake(report="short report")
    utility = UtilityModelFake()
    deps = _deps(main_fake=main, utility_fake=utility, search=search, time_limit_s=0.0)

    result = await run_research(_PLAN, "q", deps, lambda body: None)

    assert result.rounds == 0
    assert search.calls == []
    assert result.report == "short report"
    assert main.report_calls == 1


# --- cooperative cancellation ----------------------------------------------------
async def test_cancellation_is_checked_between_rounds():
    hit = SearchResult(title="A", url="https://example.com/a", snippet="s")
    search = FakeSearch(hits={"q1": [hit], "q2": [hit]})
    fetcher = FakeFetcher(
        pages={
            "https://example.com/a": FetchedPage(
                url="https://example.com/a", title="A", content="c"
            )
        }
    )

    main = MainModelFake(
        queries_by_round=[["q1"], ["q2"]],
        refine_by_round=[("a1", ["gap"]), ("a2", ["gap"])],
    )
    utility = UtilityModelFake(claim_by_call=["c1", "c2"])
    deps = _deps(
        main_fake=main,
        utility_fake=utility,
        search=search,
        fetcher=fetcher,
        round_floor=10,
        # Flips true once round 1's analyzing phase (its last check point) has run —
        # so the *next* check, at round 2's top, is the one that trips.
        cancel_requested=lambda: main.refine_calls >= 1,
    )

    with pytest.raises(asyncio.CancelledError):
        await run_research(_PLAN, "q", deps, lambda body: None)

    assert main.query_calls == 1  # round 2's planning phase never started
    assert search.calls == ["q1"]


# --- worker failure isolation ----------------------------------------------------
async def test_one_fetch_failure_does_not_lose_the_round():
    ok = SearchResult(title="Good", url="https://example.com/ok", snippet="s")
    bad = SearchResult(title="Bad", url="https://example.com/bad", snippet="s")
    search = FakeSearch(hits={"q1": [ok, bad]})
    fetcher = FakeFetcher(
        pages={
            "https://example.com/ok": FetchedPage(
                url="https://example.com/ok", title="Good", content="c"
            )
        },
        fail=frozenset({"https://example.com/bad"}),
    )
    main = MainModelFake(queries_by_round=[["q1"]], refine_by_round=[("done", [])])
    utility = UtilityModelFake(claim_by_call=["the only claim"])
    deps = _deps(
        main_fake=main, utility_fake=utility, search=search, fetcher=fetcher, max_concurrency=2
    )

    events = []
    result = await run_research(_PLAN, "q", deps, events.append)

    assert result.sources == 1  # the failed fetch lost only its own source
    citations = [e for e in events if getattr(e, "type", None) == "citation.added"]
    assert [c.url for c in citations] == ["https://example.com/ok"]


# --- writer sees only the ledger -------------------------------------------------
async def test_writer_prompt_carries_only_ledger_evidence():
    hit = SearchResult(title="Src", url="https://example.com/x", snippet="s")
    search = FakeSearch(hits={"q1": [hit]})
    fetcher = FakeFetcher(
        pages={
            "https://example.com/x": FetchedPage(
                url="https://example.com/x",
                title="Src",
                content="RAW_PAGE_TEXT_NOT_A_CLAIM and some other detail",
            )
        }
    )
    main = MainModelFake(queries_by_round=[["q1"]], refine_by_round=[("evolving draft", [])])
    utility = UtilityModelFake(claim_by_call=["the extracted claim"])
    deps = _deps(main_fake=main, utility_fake=utility, search=search, fetcher=fetcher)

    await run_research(_PLAN, "q", deps, lambda body: None)

    prompt = main.captured_report_prompt
    assert prompt is not None
    assert "the extracted claim" in prompt
    assert "https://example.com/x" in prompt
    # Raw fetched content and the analyst's intermediate draft never reach the writer.
    assert "RAW_PAGE_TEXT_NOT_A_CLAIM" not in prompt
    assert "evolving draft" not in prompt


# --- the documented event sequence for a 2-round run -----------------------------
async def test_event_sequence_for_a_two_round_run_matches_the_documented_frames():
    hit_a = SearchResult(title="A", url="https://example.com/a", snippet="s")
    hit_b = SearchResult(title="B", url="https://example.com/b", snippet="s")
    search = FakeSearch(hits={"q1": [hit_a], "q2": [hit_b]})
    fetcher = FakeFetcher(
        pages={
            "https://example.com/a": FetchedPage(
                url="https://example.com/a", title="A", content="ca"
            ),
            "https://example.com/b": FetchedPage(
                url="https://example.com/b", title="B", content="cb"
            ),
        }
    )
    main = MainModelFake(
        queries_by_round=[["q1"], ["q2"]],
        refine_by_round=[("partial", ["gap2"]), ("final", [])],
        report="REPORT",
    )
    utility = UtilityModelFake(claim_by_call=["claim a", "claim b"], comprehensive_by_call=[True])
    deps = _deps(
        main_fake=main, utility_fake=utility, search=search, fetcher=fetcher, round_floor=2
    )

    events = []
    result = await run_research(_PLAN, "q", deps, events.append)

    frames = [(getattr(e, "type", None), getattr(e, "title", None)) for e in events]
    assert frames == [
        ("step.started", "planning"),
        ("step.completed", None),
        ("step.started", "searching"),
        ("step.completed", None),
        ("step.started", "reading"),
        ("citation.added", "A"),
        ("step.completed", None),
        ("tool.progress", None),
        ("step.started", "analyzing"),
        ("step.completed", None),
        ("step.started", "planning"),
        ("step.completed", None),
        ("step.started", "searching"),
        ("step.completed", None),
        ("step.started", "reading"),
        ("citation.added", "B"),
        ("step.completed", None),
        ("tool.progress", None),
        ("step.started", "analyzing"),
        ("step.completed", None),
        ("step.started", "writing"),
        ("step.completed", None),
    ]
    # citation.added lands inside each round's "reading" phase, in first-seen order —
    # the same order the writer's numbered source list uses.
    citation_urls = [e.url for e in events if getattr(e, "type", None) == "citation.added"]
    assert citation_urls == ["https://example.com/a", "https://example.com/b"]
    progress = [e for e in events if getattr(e, "type", None) == "tool.progress"]
    assert progress[0].tool_call_id == "research-round-1"
    assert progress[0].partial == "1 sources, 1 findings"
    assert progress[1].tool_call_id == "research-round-2"
    assert progress[1].partial == "2 sources, 2 findings"
    assert result.rounds == 2
    assert result.report == "REPORT"
