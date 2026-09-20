"""Claim-level attribution: the trigger, the extraction, and what it refuses to hide.

The four things pinned here are the four ways this feature can go wrong quietly:

- it fires on a thread that never asked for it, and every normal turn pays for a
  background model call nobody wanted;
- a claim its own source does not support vanishes instead of being reported, which is
  the exact defect the whole pass exists to find;
- a bad character offset is passed through and the client highlights the wrong sentence;
- an empty or failed extraction writes something, and the panel says the answer made no
  checkable claims when in fact nothing was read.
"""

from __future__ import annotations

import pytest
from pydantic_ai import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from agent.attribution import (
    ExtractedClaim,
    _validated,
    attribute_answer,
    extract_claims,
    should_attribute,
    tool_results,
)
from core.citations import Citation
from core.config import Settings
from core.db import init_db, make_engine
from core.vault import Vault
from runs import Run, RunStream
from services.attributions import Claim, ConversationAttributions, SourceRecord

OWNER = "operator"
CONV = "conv-1"
MESSAGE = "msg-1"

ANSWER = "The reactor was cold. The budget doubled in 2024."


def _source(key: str = "https://a.example", text: str = "the reactor was cold") -> SourceRecord:
    return SourceRecord(citation=Citation(url=key, title="A page"), text=text)


def _settings(**over) -> Settings:
    return Settings(
        attribution_timeout_s=5.0,
        attribution_max_tokens=512,
        attribution_max_sources=8,
        attribution_source_chars=500,
        **over,
    )


@pytest.fixture
async def attributions(tmp_path):
    vault = Vault(tmp_path / "keyfile.json")
    await vault.setup("correct horse battery staple")
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    return ConversationAttributions(engine, vault)


def _reader(claims: list[dict]) -> FunctionModel:
    """A stand-in for the utility model that answers with exactly ``claims``."""

    def respond(messages, info: AgentInfo) -> ModelResponse:
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, {"claims": claims})]
        )

    return FunctionModel(respond)


def _run() -> Run:
    return Run(id="run-1", kind="chat", owner_id=OWNER, stream=RunStream())


# --- the trigger ------------------------------------------------------------------


def test_a_non_research_thread_is_never_read_back():
    """The pass is off for every mode that does not declare itself worth checking, and
    the check is cheap enough to sit in front of everything that costs anything."""
    assert not should_attribute(
        _settings(), mode="normal", answer=ANSWER, sources=[_source()]
    )
    assert not should_attribute(_settings(), mode="code", answer=ANSWER, sources=[_source()])
    assert should_attribute(_settings(), mode="research", answer=ANSWER, sources=[_source()])


def test_a_stored_mode_nobody_recognises_reads_as_the_mode_that_does_least():
    """A row written by another build must not switch a background call on."""
    assert not should_attribute(
        _settings(), mode="archaeology", answer=ANSWER, sources=[_source()]
    )


def test_a_turn_with_nothing_to_check_is_skipped():
    assert not should_attribute(_settings(), mode="research", answer="", sources=[_source()])
    assert not should_attribute(_settings(), mode="research", answer="   ", sources=[_source()])
    # Answered from what the model already knew: no sources retained, nothing to ground
    # a claim in, and reporting every sentence as unsupported would be a lie about a turn
    # that never claimed to be reading anything.
    assert not should_attribute(_settings(), mode="research", answer=ANSWER, sources=[])


def test_the_operator_can_switch_it_off():
    assert not should_attribute(
        _settings(attribution_enabled=False),
        mode="research",
        answer=ANSWER,
        sources=[_source()],
    )


async def test_a_non_research_thread_makes_no_model_call(attributions):
    """The trigger's whole promise, pinned at the entry point rather than at the
    predicate: a model that raises on contact proves nothing reached it."""

    def explode(messages, info: AgentInfo) -> ModelResponse:  # pragma: no cover — must not run
        raise AssertionError("the extraction model was called on a non-research thread")

    claims = await attribute_answer(
        _run(),
        answer=ANSWER,
        results=[{"url": "https://a.example", "title": "A page", "content": "anything"}],
        message_id=MESSAGE,
        conversation_id=CONV,
        owner_id=OWNER,
        model=FunctionModel(explode),
        reasoning_off=None,
        settings=_settings(),
        mode="normal",
        attributions=attributions,
    )
    assert claims == []
    assert await attributions.for_conversation(OWNER, CONV) == []


# --- an ungrounded claim is a row ------------------------------------------------


async def test_a_claim_its_own_source_does_not_support_surfaces_as_a_row(attributions):
    """The defect the feature exists to find: the answer points at a page, and the page
    does not say it. The row keeps its source so the operator can go and look."""
    model = _reader(
        [
            {
                "claim": "The reactor was cold.",
                "source_key": "https://a.example",
                "passage": "the reactor was cold",
                "confidence": "high",
            },
            {
                "claim": "The budget doubled in 2024.",
                "source_key": "https://a.example",
                "passage": "",
                "confidence": "low",
            },
        ]
    )
    claims = await attribute_answer(
        _run(),
        answer=ANSWER,
        results=[
            {"url": "https://a.example", "title": "A page", "content": "the reactor was cold"}
        ],
        message_id=MESSAGE,
        conversation_id=CONV,
        owner_id=OWNER,
        model=model,
        reasoning_off=None,
        settings=_settings(),
        mode="research",
        attributions=attributions,
    )
    assert [c.grounded for c in claims] == [True, False]
    ungrounded = claims[1]
    assert ungrounded.claim == "The budget doubled in 2024."
    # The source survives the failure to ground — it is the thing to go and check.
    assert ungrounded.source_key == "https://a.example"
    assert ungrounded.source_url == "https://a.example"
    assert ungrounded.passage is None


async def test_an_ungrounded_claim_survives_the_reload(attributions):
    await attributions.replace(
        OWNER,
        CONV,
        MESSAGE,
        [Claim(claim="unsupported", grounded=False, source_key="https://a.example")],
    )
    [stored] = await attributions.for_conversation(OWNER, CONV)
    assert stored.message_id == MESSAGE
    assert [(c.claim, c.grounded, c.source_key) for c in stored.claims] == [
        ("unsupported", False, "https://a.example")
    ]


def test_a_source_key_the_run_never_retained_is_discarded_and_the_claim_kept():
    """A reader that names something that was never read has grounded nothing — but the
    claim it read out of the answer is still a real claim."""
    [claim] = _validated(
        [ExtractedClaim(claim="The reactor was cold.", source_key="https://elsewhere.example",
                        passage="something")],
        ANSWER,
        [_source()],
    )
    assert claim.grounded is False
    assert claim.source_key is None
    assert claim.passage is None


# --- offsets ----------------------------------------------------------------------


def test_a_good_offset_is_kept():
    [claim] = _validated(
        [ExtractedClaim(claim="The reactor was cold.", offset=0)], ANSWER, [_source()]
    )
    assert claim.offset == 0


def test_a_wrong_offset_is_dropped_and_the_claim_kept():
    """A highlight on the neighbouring sentence is a worse lie than no highlight, and
    throwing the claim away instead would discard the part that was right."""
    [claim] = _validated(
        [ExtractedClaim(claim="The reactor was cold.", offset=7)], ANSWER, [_source()]
    )
    assert claim.claim == "The reactor was cold."
    assert claim.offset is None


def test_an_offset_past_the_end_is_dropped():
    for offset in (-1, len(ANSWER), len(ANSWER) + 500):
        [claim] = _validated(
            [ExtractedClaim(claim="The reactor was cold.", offset=offset)], ANSWER, [_source()]
        )
        assert claim.offset is None


def test_an_offset_at_a_later_occurrence_is_checked_where_it_points():
    answer = "alpha beta alpha"
    [claim] = _validated([ExtractedClaim(claim="alpha", offset=11)], answer, [_source()])
    assert claim.offset == 11


def test_a_claim_with_no_text_is_dropped_outright():
    assert _validated([ExtractedClaim(claim="   ")], ANSWER, [_source()]) == []


# --- the empty degrade ------------------------------------------------------------


async def test_an_empty_extraction_writes_nothing(attributions):
    """Nothing read is not the same statement as "this answer made no checkable claims",
    so no row is written and the panel keeps the message-level sources it had."""
    claims = await attribute_answer(
        _run(),
        answer=ANSWER,
        results=[{"url": "https://a.example", "title": "A page", "content": "body"}],
        message_id=MESSAGE,
        conversation_id=CONV,
        owner_id=OWNER,
        model=_reader([]),
        reasoning_off=None,
        settings=_settings(),
        mode="research",
        attributions=attributions,
    )
    assert claims == []
    assert await attributions.for_conversation(OWNER, CONV) == []


async def test_a_failing_reader_degrades_silently():
    def explode(messages, info: AgentInfo) -> ModelResponse:
        raise RuntimeError("the endpoint is down")

    assert (
        await extract_claims(
            FunctionModel(explode),
            ANSWER,
            [_source()],
            timeout_s=5.0,
            max_tokens=256,
            max_sources=8,
            source_chars=500,
        )
        == []
    )


async def test_no_utility_model_bound_degrades_without_storing(attributions):
    claims = await attribute_answer(
        _run(),
        answer=ANSWER,
        results=[{"url": "https://a.example", "title": "A page", "content": "body"}],
        message_id=MESSAGE,
        conversation_id=CONV,
        owner_id=OWNER,
        model=None,
        reasoning_off=None,
        settings=_settings(),
        mode="research",
        attributions=attributions,
    )
    assert claims == []
    assert await attributions.for_conversation(OWNER, CONV) == []


# --- `cited` gets its first producer ----------------------------------------------


async def test_a_grounded_source_is_announced_as_cited(attributions):
    run = _run()
    await attribute_answer(
        run,
        answer=ANSWER,
        results=[
            {"url": "https://a.example", "title": "A page", "content": "the reactor was cold"}
        ],
        message_id=MESSAGE,
        conversation_id=CONV,
        owner_id=OWNER,
        model=_reader(
            [
                {
                    "claim": "The reactor was cold.",
                    "source_key": "https://a.example",
                    "passage": "the reactor was cold",
                    "confidence": "high",
                },
                {
                    "claim": "The budget doubled in 2024.",
                    "source_key": "https://a.example",
                    "passage": "",
                },
            ]
        ),
        reasoning_off=None,
        settings=_settings(),
        mode="research",
        attributions=attributions,
    )
    frames = [e.body for e in run.stream.replay() if e.body.type == "citation.added"]
    # One per source, not per claim — the rung is a fact about the source — and the
    # ungrounded claim on the same page contributes nothing to it.
    assert [(f.key, f.engagement) for f in frames] == [("https://a.example", "cited")]
    assert frames[0].snippet == "the reactor was cold"


async def test_an_ungrounded_answer_announces_nothing(attributions):
    run = _run()
    await attribute_answer(
        run,
        answer=ANSWER,
        results=[{"url": "https://a.example", "title": "A page", "content": "unrelated"}],
        message_id=MESSAGE,
        conversation_id=CONV,
        owner_id=OWNER,
        model=_reader([{"claim": "The reactor was cold.", "source_key": "", "passage": ""}]),
        reasoning_off=None,
        settings=_settings(),
        mode="research",
        attributions=attributions,
    )
    assert [e.body for e in run.stream.replay() if e.body.type == "citation.added"] == []


# --- replacing, and forgetting --------------------------------------------------


async def test_a_second_reading_supersedes_the_first(attributions):
    await attributions.replace(OWNER, CONV, MESSAGE, [Claim(claim="one", grounded=False)])
    await attributions.replace(OWNER, CONV, MESSAGE, [Claim(claim="two", grounded=False)])
    [stored] = await attributions.for_conversation(OWNER, CONV)
    assert [c.claim for c in stored.claims] == ["two"]


async def test_deleting_a_thread_takes_its_readings(attributions):
    await attributions.replace(OWNER, CONV, MESSAGE, [Claim(claim="one", grounded=False)])
    await attributions.delete_for_conversation(OWNER, CONV)
    assert await attributions.for_conversation(OWNER, CONV) == []


async def test_a_locked_vault_costs_a_panel_and_never_an_error(tmp_path):
    vault = Vault(tmp_path / "keyfile.json")
    await vault.setup("correct horse battery staple")
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    store = ConversationAttributions(engine, vault)
    await store.replace(OWNER, CONV, MESSAGE, [Claim(claim="one", grounded=True)])
    vault.lock()
    assert await store.for_conversation(OWNER, CONV) == []
    assert await store.replace(OWNER, CONV, MESSAGE, [Claim(claim="two", grounded=True)]) is False


# --- what the live caller hands over ---------------------------------------------


def test_tool_results_are_read_off_the_turns_own_messages():
    from pydantic_ai import ModelRequest, ToolReturnPart, UserPromptPart

    messages = [
        ModelRequest(parts=[UserPromptPart("what happened?")]),
        ModelRequest(
            parts=[
                ToolReturnPart(tool_name="web_fetch", content={"url": "u", "content": "c"},
                               tool_call_id="1"),
                ToolReturnPart(tool_name="web_search", content={"results": []}, tool_call_id="2"),
            ]
        ),
    ]
    assert tool_results(messages) == [{"url": "u", "content": "c"}, {"results": []}]
