"""Conversation compaction — folding older turns into a utility-model summary.

The product's **one** context reduction, and the only one that fires on measured pressure —
the pressure-blind reductions (tool-result digesting, the attachment inline cap, the sandbox
output trim) are gone. What these guard, in order of how much damage getting them wrong
would do:

- **The persistence index.** ``agent/engine.py`` records a turn as
  ``result.all_messages()[start:]`` with ``start = len(model_history)``. The replay view
  reorders the tree, so if its length ever stopped matching what it represents, every turn
  after a compaction would persist the wrong slice.
- **Branch safety.** A checkpoint grafted onto a reseated leaf would re-parent the incoming
  answer out of its own version set, silently breaking version switching.
- **The boundary.** Mid-run steering messages persist as their own user requests, so
  "keep the last two turns" must not be fooled into keeping two asides.
- **Containment.** The summary is a real message row; it must not reach the listing
  preview, the message count, cross-chat search, or a transcript read.
"""

from __future__ import annotations

import pytest
from pydantic_ai import (
    BinaryContent,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RequestUsage

from agent import build_chat_orchestrator
from agent.history import merge_consecutive_requests
from agent.summarize import (
    build_auto_compact_policy,
    compact_conversation,
    render_transcript,
    should_compact,
    summarize_history,
)
from core.config import Settings, get_settings
from prompts.utility import COMPACT_PREAMBLE
from routes.deps import OPERATOR_ID
from runs import RunStatus
from services.conversation_view import estimate_tokens

from ._helpers import client_app, patch_model_resolution


def _turn(prompt: str, answer: str) -> list:
    return [
        ModelRequest(parts=[UserPromptPart(content=prompt)]),
        ModelResponse(parts=[TextPart(content=answer)]),
    ]


def _texts(messages: list) -> list[str]:
    """Every message's flattened text, for asserting on shape without part surgery."""
    out = []
    for message in messages:
        for part in message.parts:
            content = getattr(part, "content", None)
            if isinstance(content, str):
                out.append(content)
    return out


async def _compact(store, cid: str, *, keep_turns: int = 2, summary: str = "SUMMARY"):
    """Run a compaction with a fixed summary — the boundary logic under test, not the model."""
    plan = await store.compaction_plan(cid, keep_turns=keep_turns)
    if plan is None:
        return None
    return store.record_compaction(
        cid,
        summary=summary,
        through_id=plan.through_id,
        expected_leaf_id=plan.expected_leaf_id,
    )


# --- the replay view ---------------------------------------------------------


async def test_model_history_hoists_the_summary_and_keeps_the_tail():
    """The model reads the summary as a preamble, then the retained turns verbatim —
    and the *full* history is untouched, since three callers depend on it."""
    async with client_app() as (_client, app):
        store = app.state.conversations
        cid = await store.create_conversation(OPERATOR_ID)
        for i in range(4):
            store.record(cid, _turn(f"q{i}", f"a{i}"))

        full_before = _texts(await store.history(cid))
        assert await _compact(store, cid, keep_turns=2) is not None

        # The transcript keeps every original turn (the checkpoint is appended, not
        # substituted) — `history()` must not have lost a thing.
        assert _texts(await store.history(cid))[: len(full_before)] == full_before

        # The model sees: summary, then the last two exchanges. q0/a0 and q1/a1 are gone.
        assert _texts(await store.model_history(cid)) == [
            "SUMMARY",
            "q2",
            "a2",
            "q3",
            "a3",
        ]


async def test_keep_turns_zero_retains_nothing_after_the_boundary():
    """The default. `compaction_plan` cuts at `len(path)` rather than at a turn start, so
    the fold covers the *whole* thread and the model's replay is the summary alone — no
    retained tail restating what the summary already says."""
    async with client_app() as (_client, app):
        store = app.state.conversations
        cid = await store.create_conversation(OPERATOR_ID)
        for i in range(4):
            store.record(cid, _turn(f"q{i}", f"a{i}"))

        plan = await store.compaction_plan(cid, keep_turns=0)
        assert plan is not None
        assert len(plan.messages) == 8  # every message on the path, q0/a0 … q3/a3
        assert await _compact(store, cid, keep_turns=0) is not None

        assert _texts(await store.model_history(cid)) == ["SUMMARY"]
        # And nothing was destroyed — the operator's transcript still has all of it.
        assert _texts(await store.history(cid))[:8] == [
            "q0",
            "a0",
            "q1",
            "a1",
            "q2",
            "a2",
            "q3",
            "a3",
        ]


async def test_keep_turns_zero_still_folds_a_single_turn_thread():
    """With no tail to retain there is no minimum thread length — one exchange is
    foldable, where `keep_turns=2` would (rightly) find nothing to do."""
    async with client_app() as (_client, app):
        store = app.state.conversations
        cid = await store.create_conversation(OPERATOR_ID)
        store.record(cid, _turn("q0", "a0"))

        assert await store.compaction_plan(cid, keep_turns=2) is None
        plan = await store.compaction_plan(cid, keep_turns=0)
        assert plan is not None and len(plan.messages) == 2


async def test_a_second_compaction_at_keep_turns_zero_absorbs_the_first():
    """The never-reach-past-an-earlier-checkpoint rule has to hold at 0 too, where the
    boundary is the end of the path rather than a turn start."""
    async with client_app() as (_client, app):
        store = app.state.conversations
        cid = await store.create_conversation(OPERATOR_ID)
        for i in range(2):
            store.record(cid, _turn(f"q{i}", f"a{i}"))
        assert await _compact(store, cid, keep_turns=0, summary="FIRST") is not None
        for i in range(2, 4):
            store.record(cid, _turn(f"q{i}", f"a{i}"))

        plan = await store.compaction_plan(cid, keep_turns=0)
        assert plan is not None
        # The first summary plus what followed it — never the original turns again.
        assert _texts(plan.messages) == ["FIRST", "q2", "a2", "q3", "a3"]
        assert await _compact(store, cid, keep_turns=0, summary="SECOND") is not None
        assert _texts(await store.model_history(cid)) == ["SECOND"]


async def test_model_history_is_unchanged_without_a_checkpoint():
    async with client_app() as (_client, app):
        store = app.state.conversations
        cid = await store.create_conversation(OPERATOR_ID)
        store.record(cid, _turn("q", "a"))
        assert _texts(await store.model_history(cid)) == _texts(await store.history(cid))


async def test_the_replay_view_survives_a_cold_reload():
    """`compacted`/`compacted_through` must rehydrate from the DB, or a restart would
    silently replay the whole folded history again."""
    async with client_app() as (_client, app):
        store = app.state.conversations
        cid = await store.create_conversation(OPERATOR_ID)
        for i in range(4):
            store.record(cid, _turn(f"q{i}", f"a{i}"))
        assert await _compact(store, cid, keep_turns=2) is not None

        warm = _texts(await store.model_history(cid))
        await store._worker.join()
        store._cache.clear()
        assert _texts(await store.model_history(cid)) == warm


async def test_the_persistence_index_still_selects_exactly_the_new_turn():
    """`start = len(model_history)` is what the engine slices a turn out of
    `all_messages()` at. The replay view reorders the tree, so this is the assertion
    that reordering never broke the arithmetic."""
    async with client_app() as (_client, app):
        store = app.state.conversations
        cid = await store.create_conversation(OPERATOR_ID)
        for i in range(4):
            store.record(cid, _turn(f"q{i}", f"a{i}"))
        assert await _compact(store, cid, keep_turns=2) is not None

        replayed = await store.model_history(cid)
        start = len(replayed)
        # What a turn hands back: the history it was given plus its own new messages.
        all_messages = [*replayed, *_turn("q4", "a4")]
        store.record(cid, all_messages[start:])

        await store._worker.join()
        store._cache.clear()
        # The new turn landed once, in order, on the active path — not duplicated and
        # not truncated.
        assert _texts(await store.history(cid))[-2:] == ["q4", "a4"]
        assert _texts(await store.model_history(cid)) == [
            "SUMMARY",
            "q2",
            "a2",
            "q3",
            "a3",
            "q4",
            "a4",
        ]


# --- boundary selection ------------------------------------------------------


async def test_nothing_to_compact_when_the_thread_is_short():
    async with client_app() as (_client, app):
        store = app.state.conversations
        cid = await store.create_conversation(OPERATOR_ID)
        store.record(cid, _turn("q0", "a0"))
        store.record(cid, _turn("q1", "a1"))
        assert await store.compaction_plan(cid, keep_turns=2) is None


async def test_a_second_compaction_never_uncovers_the_first():
    """Each compaction folds only the region after the previous checkpoint, so the older
    summary is absorbed into the newer one rather than resurfacing as a plain turn."""
    async with client_app() as (_client, app):
        store = app.state.conversations
        cid = await store.create_conversation(OPERATOR_ID)
        for i in range(4):
            store.record(cid, _turn(f"q{i}", f"a{i}"))
        assert await _compact(store, cid, keep_turns=2, summary="FIRST") is not None
        for i in range(4, 8):
            store.record(cid, _turn(f"q{i}", f"a{i}"))
        assert await _compact(store, cid, keep_turns=2, summary="SECOND") is not None

        replayed = _texts(await store.model_history(cid))
        assert replayed == ["SECOND", "q6", "a6", "q7", "a7"]
        assert "FIRST" not in replayed  # absorbed, not re-exposed


async def test_the_folded_input_is_the_replay_view_not_the_raw_transcript():
    """A second compaction summarizes the *first summary* plus what followed — never the
    original turns a second time, which would defeat the point of the first pass."""
    async with client_app() as (_client, app):
        store = app.state.conversations
        cid = await store.create_conversation(OPERATOR_ID)
        for i in range(4):
            store.record(cid, _turn(f"q{i}", f"a{i}"))
        assert await _compact(store, cid, keep_turns=2, summary="FIRST") is not None
        for i in range(4, 8):
            store.record(cid, _turn(f"q{i}", f"a{i}"))

        plan = await store.compaction_plan(cid, keep_turns=2)
        assert plan is not None
        folded = _texts(plan.messages)
        assert folded[0] == "FIRST"
        assert "q0" not in folded and "q1" not in folded  # already inside FIRST


async def test_mid_run_steering_messages_do_not_count_as_turns():
    """A message sent while a run was executing persists as its own user request right
    behind the tool-return request it was injected into. Counting bare user prompts would
    keep two of those asides verbatim and fold a real exchange instead."""
    async with client_app() as (_client, app):
        store = app.state.conversations
        cid = await store.create_conversation(OPERATOR_ID)
        store.record(cid, _turn("q0", "a0"))
        store.record(cid, _turn("q1", "a1"))
        # A tool-using turn with two steering messages split out behind the tool return.
        store.record(
            cid,
            [
                ModelRequest(parts=[UserPromptPart(content="q2")]),
                ModelResponse(parts=[ToolCallPart(tool_name="t", args={}, tool_call_id="c1")]),
                ModelRequest(parts=[ToolReturnPart(tool_name="t", content="r", tool_call_id="c1")]),
                ModelRequest(parts=[UserPromptPart(content="aside-1")]),
                ModelRequest(parts=[UserPromptPart(content="aside-2")]),
                ModelResponse(parts=[TextPart(content="a2")]),
            ],
        )
        plan = await store.compaction_plan(cid, keep_turns=2)
        assert plan is not None
        folded = _texts(plan.messages)
        # Two turn starts kept = q1's and q2's exchanges; only q0's folds. If the asides
        # had counted, q1 would have been folded away too.
        assert folded == ["q0", "a0"]
        assert await _compact(store, cid, keep_turns=2) is not None
        assert _texts(await store.model_history(cid))[:2] == ["SUMMARY", "q1"]


async def test_no_compaction_while_the_leaf_is_a_branch_point():
    """A regenerate has reseated the leaf and its run hasn't recorded yet. Appending a
    checkpoint there would make the new answer a child of the checkpoint instead of a
    sibling of the old one, quietly breaking version switching."""
    async with client_app() as (_client, app):
        store = app.state.conversations
        cid = await store.create_conversation(OPERATOR_ID)
        for i in range(4):
            store.record(cid, _turn(f"q{i}", f"a{i}"))
        assert await store.compaction_plan(cid, keep_turns=2) is not None

        answer = [m for m in await store.messages_view(cid) if m.role == "assistant"][-1]
        assert await store.regenerate_point(cid, answer.id)
        assert await store.compaction_plan(cid, keep_turns=2) is None

        # Once the regenerated answer lands, the leaf is childless again and it resumes.
        store.record(cid, [ModelResponse(parts=[TextPart(content="a3-again")])])
        assert await store.compaction_plan(cid, keep_turns=2) is not None


async def test_record_compaction_refuses_a_stale_plan():
    """Summarizing takes seconds, and the conversation claim blocks runs but not a version
    switch — so the leaf is re-checked at record time and a moved one drops the summary."""
    async with client_app() as (_client, app):
        store = app.state.conversations
        cid = await store.create_conversation(OPERATOR_ID)
        for i in range(4):
            store.record(cid, _turn(f"q{i}", f"a{i}"))
        plan = await store.compaction_plan(cid, keep_turns=2)
        assert plan is not None

        # The operator regenerates while the summary is being written.
        answer = [m for m in await store.messages_view(cid) if m.role == "assistant"][-1]
        assert await store.regenerate_point(cid, answer.id)

        assert (
            store.record_compaction(
                cid,
                summary="SUMMARY",
                through_id=plan.through_id,
                expected_leaf_id=plan.expected_leaf_id,
            )
            is None
        )


# --- the threshold -----------------------------------------------------------


def _response(input_tokens: int, output_tokens: int = 0) -> ModelResponse:
    return ModelResponse(
        parts=[TextPart(content="x")],
        usage=RequestUsage(input_tokens=input_tokens, output_tokens=output_tokens),
    )


@pytest.mark.parametrize(
    ("used", "expected"),
    [(9_000, False), (9_500, True), (9_900, True)],
)
def test_should_compact_measures_against_the_window(used: int, expected: bool):
    assert should_compact([_response(used)], 10_000, 0.95) is expected


def test_should_compact_declines_without_a_declared_window():
    """No ceiling to measure against — compacting on a guess would fold a thread that was
    never under pressure."""
    assert should_compact([_response(999_999)], None, 0.95) is False


def test_should_compact_falls_back_to_an_estimate_when_usage_is_unreported():
    """Local servers commonly report `input_tokens=0`, which `context_footprint` treats as
    unmeasured. Without the estimate the feature would be dead on exactly that setup."""
    big = ModelRequest(parts=[UserPromptPart(content="x" * 40_000)])
    assert should_compact([big, ModelResponse(parts=[TextPart(content="y")])], 10_000, 0.95)


def test_the_estimate_ignores_binary_content():
    """A retained inline image is base64 in the blob; measuring it by length would read one
    screenshot as hundreds of thousands of phantom tokens."""
    image = BinaryContent(data=b"\x00" * 100_000, media_type="image/png")
    message = ModelRequest(parts=[UserPromptPart(content=["hi", image])])
    assert estimate_tokens([message]) < 10


# --- the summarizer ----------------------------------------------------------


def test_render_transcript_labels_turns_and_keeps_tool_traffic():
    rendered = render_transcript(
        [
            ModelRequest(parts=[UserPromptPart(content="find it")]),
            ModelResponse(parts=[ToolCallPart(tool_name="web", args={"q": "x"}, tool_call_id="1")]),
            ModelRequest(
                parts=[ToolReturnPart(tool_name="web", content="found", tool_call_id="1")]
            ),
            ModelResponse(parts=[TextPart(content="here you go")]),
        ]
    )
    assert "OPERATOR: find it" in rendered
    assert "ASSISTANT called web" in rendered
    assert "TOOL web returned: found" in rendered
    assert "ASSISTANT: here you go" in rendered


def test_render_transcript_elides_the_middle_when_over_budget():
    """What is being folded is most of the *main* model's window; the utility model may be
    smaller. Both ends are kept — how the thread opened and where it currently stands — and
    the middle goes, rather than the head-only cut a plain truncation would make."""
    messages = [ModelRequest(parts=[UserPromptPart(content=f"message-{i:02d}")]) for i in range(60)]
    rendered = render_transcript(messages, max_input_tokens=50)  # 200 chars
    assert "characters of the middle omitted" in rendered
    assert "message-00" in rendered  # the opening survives
    assert "message-59" in rendered  # so does the current state
    assert "message-30" not in rendered  # the middle is what pays


async def test_summarize_history_degrades_to_none_on_failure():
    """A summarizer outage must leave the thread uncompacted, never fail the turn it was
    about to make room for."""

    class _Boom(TestModel):
        async def request(self, *args, **kwargs):
            raise RuntimeError("model down")

    result = await summarize_history(_Boom(), [ModelRequest(parts=[UserPromptPart(content="hi")])])
    assert result is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("<think>weighing it up</think>the story so far", "the story so far"),
        ("<THINK>casing is the template's choice</think>\n\nthe story so far", "the story so far"),
        # A model that exhausts max_tokens mid-thought emits an *unclosed* block, whose
        # partial content Pydantic AI still returns. Left in, the summarizer's scratch
        # reasoning would become the thread's standing memory.
        ("the story so far\n<think>still reasoning when the budget ran", "the story so far"),
    ],
)
async def test_summarize_history_strips_a_leaked_think_block(raw: str, expected: str):
    """Reasoning is requested off, but the lever is best-effort: a runtime that ignores it
    inlines the chain-of-thought in the content. The summary is what the model replays for
    the rest of the thread, so a leaked block must never survive into it."""
    summary = await summarize_history(
        TestModel(custom_output_text=raw),
        [ModelRequest(parts=[UserPromptPart(content="hi")])],
    )
    assert summary == expected


async def test_summarize_history_returns_none_when_only_reasoning_came_back():
    """A reply that is *nothing but* a think block leaves no summary — better to skip the
    compaction than to store an empty checkpoint the model would replay as its memory."""
    summary = await summarize_history(
        TestModel(custom_output_text="<think>never got to the answer</think>"),
        [ModelRequest(parts=[UserPromptPart(content="hi")])],
    )
    assert summary is None


async def test_compact_conversation_end_to_end():
    async with client_app() as (_client, app):
        store = app.state.conversations
        cid = await store.create_conversation(OPERATOR_ID)
        for i in range(4):
            store.record(cid, _turn(f"q{i}", f"a{i}"))

        outcome = await compact_conversation(
            store, cid, model=TestModel(custom_output_text="the story so far"), keep_turns=2
        )
        assert outcome is not None
        # The stored summary is labelled, so the model can't read it as the operator's own
        # words once the provider merges it with the first retained prompt — and the event
        # carries the same string the divider renders on a reload.
        assert outcome.summary == f"{COMPACT_PREAMBLE}\n\nthe story so far"
        assert outcome.messages_compacted == 4  # q0/a0/q1/a1
        assert _texts(await store.model_history(cid))[0] == outcome.summary


async def test_the_outcome_reports_what_the_fold_cost():
    """The divider says "N messages folded, ~X → ~Y" — so the backend has to measure both
    ends. Coarse `estimate_tokens` figures, the same proxy the trigger measures with."""
    async with client_app() as (_client, app):
        store = app.state.conversations
        cid = await store.create_conversation(OPERATOR_ID)
        for i in range(4):
            store.record(cid, _turn(f"q{i} {'padding ' * 200}", f"a{i} {'padding ' * 200}"))

        outcome = await compact_conversation(
            store, cid, model=TestModel(custom_output_text="short"), keep_turns=0
        )
        assert outcome is not None
        assert outcome.messages_compacted == 8
        # The fold has to have actually bought room, and the numbers must be real.
        assert outcome.tokens_before > outcome.tokens_after > 0
        assert outcome.tokens_after == estimate_tokens(
            [ModelRequest(parts=[UserPromptPart(content=outcome.summary)])]
        )


async def test_the_cold_read_divider_reports_the_same_figures_as_the_event():
    """A live client renders the divider from `conversation.compacted`; a reload renders
    it from the projection. Both compute the numbers the same way, so they must agree —
    the figure must not change under the operator when they refresh the page."""
    async with client_app() as (_client, app):
        store = app.state.conversations
        cid = await store.create_conversation(OPERATOR_ID)
        for i in range(4):
            store.record(cid, _turn(f"q{i} {'padding ' * 200}", f"a{i} {'padding ' * 200}"))

        outcome = await compact_conversation(
            store, cid, model=TestModel(custom_output_text="short"), keep_turns=0
        )
        assert outcome is not None

        divider = next(v for v in await store.messages_view(cid) if v.role == "compaction")
        assert divider.id == outcome.message_id
        assert divider.messages_compacted == outcome.messages_compacted
        assert divider.tokens_before == outcome.tokens_before
        assert divider.tokens_after == outcome.tokens_after
        # And an ordinary turn carries no fold stats at all.
        user = next(v for v in await store.messages_view(cid) if v.role == "user")
        assert (user.messages_compacted, user.tokens_before, user.tokens_after) == (0, 0, 0)


async def test_a_second_folds_stats_cover_only_what_it_folded():
    """A second compaction stands in for the first summary plus what followed it — not the
    original turns all over again. Its divider must say so, on both paths."""
    async with client_app() as (_client, app):
        store = app.state.conversations
        cid = await store.create_conversation(OPERATOR_ID)
        for i in range(2):
            store.record(cid, _turn(f"q{i}", f"a{i}"))
        first = await compact_conversation(
            store, cid, model=TestModel(custom_output_text="first"), keep_turns=0
        )
        for i in range(2, 5):
            store.record(cid, _turn(f"q{i}", f"a{i}"))
        second = await compact_conversation(
            store, cid, model=TestModel(custom_output_text="second"), keep_turns=0
        )
        assert first is not None and second is not None
        assert first.messages_compacted == 4  # q0/a0/q1/a1
        assert second.messages_compacted == 7  # the first summary + q2/a2/q3/a3/q4/a4

        dividers = [v for v in await store.messages_view(cid) if v.role == "compaction"]
        assert [d.messages_compacted for d in dividers] == [4, 7]
        assert [d.tokens_before for d in dividers] == [first.tokens_before, second.tokens_before]


# --- containment -------------------------------------------------------------


async def test_a_checkpoint_stays_out_of_the_listing_search_and_transcript():
    """The summary is a real row. It must not become the sidebar preview (it is the tip
    right after a compaction), must not inflate the message count, must not be recalled by
    cross-chat search, and must not read back as something the assistant said."""
    async with client_app() as (_client, app):
        store = app.state.conversations
        cid = await store.create_conversation(OPERATOR_ID)
        for i in range(4):
            store.record(cid, _turn(f"q{i}", f"a{i}"))
        before = await store.get_summary(cid, OPERATOR_ID)
        assert await _compact(store, cid, keep_turns=2, summary="A DISTINCTIVE SUMMARY")

        after = await store.get_summary(cid, OPERATOR_ID)
        assert after.preview == before.preview  # still the last real message
        assert after.message_count == before.message_count

        await store._worker.join()
        store._cache.clear()
        cold = await store.get_summary(cid, OPERATOR_ID)
        assert "DISTINCTIVE" not in (cold.preview or "")

        search = app.state.conversation_search
        hits = await search.search(OPERATOR_ID, "DISTINCTIVE SUMMARY", limit=10)
        assert all("DISTINCTIVE" not in hit.snippet for hit in hits)

        transcript = await search.read(OPERATOR_ID, cid)
        assert "DISTINCTIVE" not in transcript.text


async def test_the_divider_renders_above_the_turns_it_kept():
    """Transcript order, not tree order: the checkpoint is appended at the tip but shown
    where the fold happened, or it would claim to have folded the turns below it."""
    async with client_app() as (_client, app):
        store = app.state.conversations
        cid = await store.create_conversation(OPERATOR_ID)
        for i in range(4):
            store.record(cid, _turn(f"q{i}", f"a{i}"))
        assert await _compact(store, cid, keep_turns=2) is not None

        views = await store.messages_view(cid)
        roles = [v.role for v in views]
        assert roles.count("compaction") == 1
        divider = roles.index("compaction")
        assert views[divider].content == "SUMMARY"
        # Everything before the divider is what was folded; q2 opens the retained tail.
        assert [v.content for v in views[:divider] if v.role == "user"] == ["q0", "q1"]
        assert [v.content for v in views[divider + 1 :] if v.role == "user"] == ["q2", "q3"]


# --- the engine trigger ------------------------------------------------------


def _loaded_turn(prompt: str, answer: str, input_tokens: int) -> list:
    """A turn whose answer reports a real prompt size, so `context_footprint` can read it."""
    return [
        ModelRequest(parts=[UserPromptPart(content=prompt)]),
        ModelResponse(
            parts=[TextPart(content=answer)],
            usage=RequestUsage(input_tokens=input_tokens, output_tokens=10),
        ),
    ]


async def _run_turn(app, cid: str, *, policy):
    """Drive one real chat turn through the orchestrator against a seeded conversation."""
    orch = build_chat_orchestrator(
        "next question",
        model=TestModel(custom_output_text="the answer"),
        categories={},
        utility_model=TestModel(custom_output_text="FOLDED AWAY"),
        store=app.state.conversations,
        conversation_id=cid,
        context_window=10_000,
        auto_compact=policy,
    )
    run = app.state.runs.submit(kind="chat", owner_id=OPERATOR_ID, orchestrator=orch)
    await run.wait()
    return run


async def test_a_full_thread_compacts_before_the_turn_and_announces_it():
    async with client_app() as (_client, app):
        store = app.state.conversations
        cid = await store.create_conversation(OPERATOR_ID)
        for i in range(3):
            store.record(cid, _loaded_turn(f"q{i}", f"a{i}", 100))
        store.record(cid, _loaded_turn("q3", "a3", 9_600))  # 96% of a 10k window

        run = await _run_turn(app, cid, policy=build_auto_compact_policy(Settings()))
        assert run.status is RunStatus.done

        events = [e.body for e in run.stream.replay() if e.body.type == "conversation.compacted"]
        assert len(events) == 1
        assert events[0].summary.endswith("FOLDED AWAY")
        assert events[0].summary.startswith(COMPACT_PREAMBLE)
        assert events[0].conversation_id == cid
        assert events[0].messages_compacted > 0
        # The event carries the cost of the fold, so the divider can state it without the
        # client counting or estimating anything itself. These fixtures fake *reported
        # usage* over near-empty text, so only the summary's own estimate is meaningful
        # here — the real before/after relationship is covered above, over real text.
        assert events[0].tokens_after == estimate_tokens(
            [ModelRequest(parts=[UserPromptPart(content=events[0].summary)])]
        )
        assert events[0].tokens_before >= 0

        # The model's view now opens on the summary, and the turn that ran persisted
        # normally on top of it.
        replayed = _texts(await store.model_history(cid))
        assert replayed[0].endswith("FOLDED AWAY")
        assert replayed[-2:] == ["next question", "the answer"]


async def test_a_store_failure_during_compaction_does_not_take_the_turn_down(monkeypatch):
    """Compaction is an optimization. If the store fails mid-fold the turn must still
    answer on the full history — the run's own context stop is the real backstop."""
    async with client_app() as (_client, app):
        store = app.state.conversations
        cid = await store.create_conversation(OPERATOR_ID)
        for i in range(3):
            store.record(cid, _loaded_turn(f"q{i}", f"a{i}", 100))
        store.record(cid, _loaded_turn("q3", "a3", 9_600))

        async def boom(*args, **kwargs):
            raise RuntimeError("store is having a day")

        monkeypatch.setattr(type(store), "compaction_plan", boom)
        run = await _run_turn(app, cid, policy=build_auto_compact_policy(Settings()))
        assert run.status is RunStatus.done
        assert not [e for e in run.stream.replay() if e.body.type == "conversation.compacted"]


async def test_a_thread_below_the_threshold_is_left_alone():
    async with client_app() as (_client, app):
        store = app.state.conversations
        cid = await store.create_conversation(OPERATOR_ID)
        for i in range(4):
            store.record(cid, _loaded_turn(f"q{i}", f"a{i}", 100))  # 1% of the window

        run = await _run_turn(app, cid, policy=build_auto_compact_policy(Settings()))
        assert run.status is RunStatus.done
        assert not [e for e in run.stream.replay() if e.body.type == "conversation.compacted"]
        assert "FOLDED AWAY" not in _texts(await store.model_history(cid))


async def test_a_disabled_policy_never_compacts_however_full():
    async with client_app() as (_client, app):
        store = app.state.conversations
        cid = await store.create_conversation(OPERATOR_ID)
        for i in range(3):
            store.record(cid, _loaded_turn(f"q{i}", f"a{i}", 100))
        store.record(cid, _loaded_turn("q3", "a3", 9_900))

        run = await _run_turn(app, cid, policy=build_auto_compact_policy(Settings(), enabled=False))
        assert run.status is RunStatus.done
        assert not [e for e in run.stream.replay() if e.body.type == "conversation.compacted"]


async def test_the_turn_after_a_compaction_persists_exactly_itself():
    """The engine's `start = len(model_history)` slice, exercised through the real
    orchestrator: the compacted turn must add its own two messages to the tree and no more."""
    async with client_app() as (_client, app):
        store = app.state.conversations
        cid = await store.create_conversation(OPERATOR_ID)
        for i in range(3):
            store.record(cid, _loaded_turn(f"q{i}", f"a{i}", 100))
        store.record(cid, _loaded_turn("q3", "a3", 9_600))
        before = len(await store.history(cid))

        run = await _run_turn(app, cid, policy=build_auto_compact_policy(Settings()))
        assert run.status is RunStatus.done

        await store._worker.join()
        store._cache.clear()
        after = _texts(await store.history(cid))
        # +1 checkpoint, +1 user request, +1 response. Nothing re-recorded, nothing dropped.
        assert len(after) == before + 3
        assert after[-2:] == ["next question", "the answer"]


async def test_the_plans_anchor_names_the_rendered_turn_the_divider_follows():
    """A live client addresses turns, not tree nodes — an assistant turn can span several
    nodes and renders as one bubble. The anchor must be the id that bubble carries, or the
    divider would land somewhere a reload disagrees with."""
    async with client_app() as (_client, app):
        store = app.state.conversations
        cid = await store.create_conversation(OPERATOR_ID)
        for i in range(4):
            store.record(cid, _turn(f"q{i}", f"a{i}"))

        plan = await store.compaction_plan(cid, keep_turns=2)
        assert plan is not None
        assert await _compact(store, cid, keep_turns=2) is not None

        views = await store.messages_view(cid)
        divider = next(i for i, v in enumerate(views) if v.role == "compaction")
        assert views[divider - 1].id == plan.anchor_id


# --- the merge normalization the index depends on ----------------------------


def test_consecutive_requests_merge_so_the_index_stays_honest():
    """Pydantic AI collapses adjacent requests when it prepares the wire format, so
    ``all_messages()`` comes back shorter than what was handed in. Normalizing first is
    what keeps ``start`` pointing at the real boundary."""
    merged = merge_consecutive_requests(
        [
            ModelRequest(parts=[UserPromptPart(content="a")]),
            ModelRequest(parts=[UserPromptPart(content="b")]),
            ModelResponse(parts=[TextPart(content="r")]),
            ModelRequest(parts=[UserPromptPart(content="c")]),
        ]
    )
    assert len(merged) == 3
    assert [p.content for p in merged[0].parts] == ["a", "b"]


async def test_the_library_really_does_merge_and_its_own_index_is_not_a_substitute():
    """Two facts this normalization rests on, checked against the installed library
    rather than assumed.

    First, Pydantic AI genuinely merges adjacent requests: hand it a history ending in
    two of them and ``all_messages()`` comes back one short, so a naive
    ``all_messages()[len(history):]`` slices past the operator's own prompt.

    Second — the reason ``start`` isn't simply replaced by ``new_messages()`` — the
    library's index is per *agent run*, and one of our turns can be several (a
    continuation, an approval resume, a verifier correction). It is right about the run
    it describes; it just isn't answering the question ``start`` answers.
    """
    from pydantic_ai import Agent
    from pydantic_ai.models.function import FunctionModel

    def reply(messages, info):
        return ModelResponse(parts=[TextPart(content="ok")])

    history = [
        ModelRequest(parts=[UserPromptPart(content="first")]),
        ModelResponse(parts=[TextPart(content="answered")]),
        # What a compaction checkpoint in front of a retained tail produces.
        ModelRequest(parts=[UserPromptPart(content="checkpoint")]),
        ModelRequest(parts=[UserPromptPart(content="tail")]),
    ]
    naive_start = len(history)

    result = await Agent(FunctionModel(reply)).run("new question", message_history=history)
    everything = result.all_messages()

    # The merge is real, and the naive index loses the operator's message because of it.
    assert len(everything) == len(history) + 1  # four in, five out — two became one
    assert not any(
        isinstance(part, UserPromptPart) and part.content == "new question"
        for message in everything[naive_start:]
        for part in message.parts
    )
    # Normalizing first is what fixes it: `start` measured against the merged list points
    # at the operator's prompt, which is what gets persisted.
    normalized = merge_consecutive_requests(history)
    assert isinstance(everything[len(normalized)], ModelRequest)
    assert any(
        isinstance(part, UserPromptPart) and part.content == "new question"
        for part in everything[len(normalized)].parts
    )


def test_the_merge_does_not_mutate_the_messages_it_was_given():
    """The store's in-memory tree shares these objects — mutating one in place would
    corrupt the durable history of every later read."""
    first = ModelRequest(parts=[UserPromptPart(content="a")])
    merge_consecutive_requests([first, ModelRequest(parts=[UserPromptPart(content="b")])])
    assert [p.content for p in first.parts] == ["a"]


async def test_a_steered_turn_replays_without_losing_the_next_turns_prompt():
    """The same index bug, reached the other way: a mid-run steering message persists as
    its own request directly behind the tool-return request it was injected into, so the
    *next* turn's history contains adjacent requests. Before normalization those merged
    inside `all_messages()` and the next turn persisted one message short — losing the
    operator's own prompt."""
    async with client_app() as (_client, app):
        store = app.state.conversations
        cid = await store.create_conversation(OPERATOR_ID)
        store.record(
            cid,
            [
                ModelRequest(parts=[UserPromptPart(content="do a thing")]),
                ModelResponse(parts=[ToolCallPart(tool_name="t", args={}, tool_call_id="c1")]),
                ModelRequest(parts=[ToolReturnPart(tool_name="t", content="r", tool_call_id="c1")]),
                ModelRequest(parts=[UserPromptPart(content="actually, also this")]),
                ModelResponse(parts=[TextPart(content="done")]),
            ],
        )
        run = await _run_turn(app, cid, policy=build_auto_compact_policy(Settings()))
        assert run.status is RunStatus.done

        await store._worker.join()
        store._cache.clear()
        assert _texts(await store.history(cid))[-2:] == ["next question", "the answer"]


# --- policy + routes ---------------------------------------------------------


def test_the_policy_resolves_from_config_defaults():
    policy = build_auto_compact_policy(get_settings())
    assert policy.enabled is True
    # 80%, not 95%: a fold at 95% leaves no room for the turn that triggered it.
    assert policy.threshold == pytest.approx(0.80)
    # The last few exchanges survive verbatim — a summary is at its most lossy about the
    # work in flight, which is exactly the work the next turn continues.
    assert policy.keep_turns == 3


def test_the_policy_takes_operator_overrides():
    policy = build_auto_compact_policy(Settings(), enabled=False, threshold=0.5)
    assert policy.enabled is False
    assert policy.threshold == pytest.approx(0.5)


async def test_chat_settings_round_trip_the_auto_compact_preferences():
    async with client_app() as (client, _app):
        body = await (await client.get("/chat/settings")).aread()
        assert b"auto_compact_enabled" in body

        resp = await client.put(
            "/chat/settings", json={"auto_compact_enabled": False, "auto_compact_threshold": 0.8}
        )
        assert resp.status_code == 200
        assert resp.json()["auto_compact_enabled"] is False
        assert resp.json()["auto_compact_threshold"] == pytest.approx(0.8)

        # A PUT touching only one group leaves the rest alone.
        resp = await client.put("/chat/settings", json={"agent_request_limit": 33})
        assert resp.json()["auto_compact_threshold"] == pytest.approx(0.8)
        assert resp.json()["auto_compact_enabled"] is False


@pytest.mark.parametrize("threshold", [0, 1.5, -0.2])
async def test_an_out_of_range_threshold_is_rejected(threshold: float):
    """0 would fire on an empty thread; above 1 it could never fire at all."""
    async with client_app() as (client, _app):
        resp = await client.put("/chat/settings", json={"auto_compact_threshold": threshold})
        assert resp.status_code == 422


async def test_the_per_conversation_override_round_trips():
    async with client_app() as (client, app):
        cid = await app.state.conversations.create_conversation(OPERATOR_ID)
        resp = await client.get(f"/conversations/{cid}/auto-compact")
        assert resp.json() == {"override": None, "effective": True}

        resp = await client.put(f"/conversations/{cid}/auto-compact", json={"override": False})
        assert resp.json() == {"override": False, "effective": False}

        # Clearing it goes back to inheriting the operator default.
        resp = await client.put(f"/conversations/{cid}/auto-compact", json={"override": None})
        assert resp.json() == {"override": None, "effective": True}


async def test_the_override_is_scoped_to_one_thread():
    """The per-thread switch is exactly that — turning folding off in one conversation
    must not reach into another, which still inherits the operator's default."""
    async with client_app() as (client, app):
        store = app.state.conversations
        muted = await store.create_conversation(OPERATOR_ID)
        other = await store.create_conversation(OPERATOR_ID)
        await client.put(f"/conversations/{muted}/auto-compact", json={"override": False})
        assert (await client.get(f"/conversations/{other}/auto-compact")).json() == {
            "override": None,
            "effective": True,
        }


async def test_manual_compact_folds_and_returns_the_refreshed_detail(monkeypatch):
    async with client_app() as (client, app):
        patch_model_resolution(monkeypatch, output_text="a hand-made summary")
        store = app.state.conversations
        cid = await store.create_conversation(OPERATOR_ID)
        for i in range(4):
            store.record(cid, _turn(f"q{i}", f"a{i}"))

        resp = await client.post(f"/conversations/{cid}/compact")
        assert resp.status_code == 200
        roles = [m["role"] for m in resp.json()["messages"]]
        assert "compaction" in roles


async def test_manual_compact_409s_when_there_is_nothing_to_fold(monkeypatch):
    # With nothing retained after the boundary, "nothing to fold" means an empty thread —
    # a single exchange is foldable, where a retained tail would have swallowed it.
    async with client_app() as (client, app):
        patch_model_resolution(monkeypatch)
        cid = await app.state.conversations.create_conversation(OPERATOR_ID)
        assert (await client.post(f"/conversations/{cid}/compact")).status_code == 409


async def test_manual_compact_409s_on_a_busy_conversation(monkeypatch):
    """It appends to the tree, so unlike retitle it must not run beside a live turn."""
    async with client_app() as (client, app):
        patch_model_resolution(monkeypatch)
        cid = await app.state.conversations.create_conversation(OPERATOR_ID)
        app.state.runs.claim(cid, OPERATOR_ID)
        try:
            assert (await client.post(f"/conversations/{cid}/compact")).status_code == 409
        finally:
            app.state.runs.release(cid, OPERATOR_ID)


async def test_manual_compact_404s_for_an_unknown_conversation(monkeypatch):
    async with client_app() as (client, _app):
        patch_model_resolution(monkeypatch)
        assert (await client.post("/conversations/nope/compact")).status_code == 404
