"""How close the context split actually is, measured against a real tokenizer.

The breakdown under the composer is the one figure that tells an operator *why* their
window is full, and the two answers it distinguishes lead to opposite actions: a thread
heavy with messages wants a compaction or a fresh start, one heavy with tool schemas
wants fewer tools switched on. Getting the ratio wrong doesn't make the readout vague, it
makes it point the wrong way — so the accuracy of the estimate is worth pinning rather
than assuming.

No provider reports a breakdown, so the split is ours: characters counted on our side and
converted at a characters-per-token rate. These tests hold that rate honest against
`cl100k` on representative content. cl100k is not the tokenizer any particular model
uses, and that is fine — what is being checked is that **prose and JSON convert at
different enough rates to be worth separating**, and that our two constants sit close to
the real ones. A per-model tokenizer would buy absolute precision the readout doesn't
spend: the parts are scaled to the provider's own total afterwards, so a bias shared by
all three cancels, and only the difference between them survives.
"""

from __future__ import annotations

import json

import pytest
from pydantic_ai import ModelRequest, ModelResponse
from pydantic_ai.messages import TextPart, ToolReturnPart, UserPromptPart
from pydantic_ai.usage import RequestUsage

from runs import TurnOverhead
from services.context_budget import (
    CHARS_PER_TOKEN_JSON,
    CHARS_PER_TOKEN_PROSE,
    compose,
)
from services.conversation_view import message_chars

tiktoken = pytest.importorskip("tiktoken", reason="calibration needs a real tokenizer")


@pytest.fixture(scope="module")
def encoder():
    return tiktoken.get_encoding("cl100k_base")


# ── Representative content ───────────────────────────────────────────────────────


def _tool_schema(name: str = "corpus_search") -> str:
    """A tool definition in exactly the shape `agent/overhead.py` serializes."""
    return json.dumps(
        {
            "name": name,
            "description": (
                "Search the indexed corpus for passages matching a natural-language "
                "query. Returns ranked excerpts with document ids and relevance scores."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query."},
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results to return.",
                        "default": 10,
                    },
                    "document_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Restrict the search to these documents.",
                    },
                },
                "required": ["query"],
            },
        },
        default=str,
    )


def _tool_result() -> dict:
    return {
        "results": [
            {
                "title": f"Result {i}: the strait remains open to commercial traffic",
                "url": f"https://en.example.org/news/{i}",
                "snippet": (
                    "CENTCOM says the strait is fully de-mined and momentum is building "
                    "after 24 tankers transited overnight, still well below pre-war levels."
                ),
                "score": 0.87,
            }
            for i in range(6)
        ]
    }


#: Varied prose, deliberately not a repeated block. A sample that repeats one sentence
#: tokenizes far better than real text does (5.3 characters per token against 4.8), which
#: would calibrate the constant against an artefact of the fixture.
_PROSE = """
The operator asked for a picture of the current situation, and the answer runs to several
paragraphs of ordinary English with the occasional proper noun in it. CENTCOM chief Admiral
Brad Cooper said the strait is fully de-mined and that momentum is building, after the US
helped twenty-four tankers transit overnight.

That figure is well below the roughly one hundred and twenty daily pre-war transits, and
several allied governments doubt the picture is as settled as stated. Insurers have not
moved their rates, which is usually the clearest signal available.

Separately, the Treasury is cutting a major Egyptian bank's operations in the UAE out of
the dollar system, part of a campaign officials describe as economic asphyxiation. Tehran's
foreign ministry called the sanctions economic terrorism and said it would respond in kind.

I can dig into any of these threads - the deal conditions, the de-mining dispute, or the
sanctions angle. Which would be most useful? There is also a longer piece on the shipping
insurance market if that is the part that matters for your purposes.
""".strip()


def _rate(encoder, text: str) -> float:
    return len(text) / len(encoder.encode(text))


# ── The constants ────────────────────────────────────────────────────────────────


def test_prose_and_json_really_do_tokenize_differently(encoder):
    """The premise the two constants rest on. If these converged, one divisor would be
    right and the split's extra machinery would be dead weight."""
    prose_rate = _rate(encoder, _PROSE)
    json_rate = _rate(encoder, _tool_schema() + json.dumps(_tool_result()))
    # JSON is denser: more tokens per character, so fewer characters per token.
    assert json_rate < prose_rate
    # And by enough to matter — a shared divisor would misweight one against the other by
    # roughly this much, which is the error the split can least afford.
    assert prose_rate - json_rate > 0.3


@pytest.mark.parametrize(
    ("constant", "sample"),
    [
        (CHARS_PER_TOKEN_PROSE, _PROSE),
        (CHARS_PER_TOKEN_JSON, _tool_schema()),
        (CHARS_PER_TOKEN_JSON, json.dumps(_tool_result())),
    ],
)
def test_each_constant_is_within_ten_percent_of_the_real_rate(encoder, constant, sample):
    """Absolute accuracy, held loosely on purpose. The parts are scaled to the provider's
    total afterwards, so what a shared bias costs is nothing; 10% is tight enough that a
    constant can't drift into being wrong about the *kind* of content it describes."""
    real = _rate(encoder, sample)
    assert abs(constant - real) / real < 0.10, f"{constant} vs measured {real:.2f}"


# ── The split ────────────────────────────────────────────────────────────────────


def _tokens(encoder, text: str) -> int:
    return len(encoder.encode(text))


def test_the_split_lands_close_to_what_a_tokenizer_says(encoder):
    """End to end, on a thread built to be adversarial: heavy tool schemas, heavy
    structured results, and a fair amount of prose — the mix where a single divisor goes
    furthest wrong."""
    schemas = "".join(_tool_schema(f"tool_{i}") for i in range(12))
    brief = _PROSE[:1500]
    result = _tool_result()
    messages = [
        ModelRequest(parts=[UserPromptPart(content="what is going on in the strait?")]),
        ModelRequest(parts=[ToolReturnPart(tool_name="search", content=result, tool_call_id="1")]),
        ModelResponse(parts=[TextPart(content=_PROSE)], usage=RequestUsage()),
    ]

    # Ground truth, part by part, from the tokenizer itself.
    truth = {
        "system": _tokens(encoder, brief),
        "tools": _tokens(encoder, schemas),
        "messages": (
            _tokens(encoder, "what is going on in the strait?")
            + _tokens(encoder, json.dumps(result))
            + _tokens(encoder, _PROSE)
        ),
    }
    used = sum(truth.values())

    split = compose(used, TurnOverhead(system=len(brief), tools=len(schemas)), messages)
    assert split is not None

    for name, actual in truth.items():
        estimated = getattr(split, name)
        error = abs(estimated - actual) / actual
        assert error < 0.15, f"{name}: estimated {estimated}, tokenizer says {actual}"


def test_the_dominant_part_is_never_misidentified(encoder):
    """The failure that would actually mislead someone. Whatever else the split gets
    wrong, the largest part has to be the largest part — that is the whole question the
    operator opens the breakdown to answer."""
    schemas = "".join(_tool_schema(f"tool_{i}") for i in range(40))
    brief = _PROSE[:800]
    # A thread that has barely said anything, against a large tool catalog: the tools
    # are the reason this window is filling, and the readout has to say so.
    messages = [ModelRequest(parts=[UserPromptPart(content="hello")])]
    split = compose(
        50_000, TurnOverhead(system=len(brief), tools=len(schemas)), messages
    )
    assert split is not None
    assert split.tools > split.messages
    assert split.tools > split.system

    # And the reverse: a long conversation against the same catalog is a messages
    # problem, not a tools problem.
    talkative = [
        ModelResponse(parts=[TextPart(content=_PROSE * 12)], usage=RequestUsage())
        for _ in range(4)
    ]
    split = compose(
        50_000, TurnOverhead(system=len(brief), tools=len(schemas)), talkative
    )
    assert split is not None
    assert split.messages > split.tools


def test_structured_results_are_credited_to_messages_not_to_tools(encoder):
    """The specific misreading this readout was shipped with. Tool *results* live in the
    conversation; only the *schemas* are overhead. Scoring a dict result as zero — which
    is what the estimator did — blamed the tool catalog for weight the search results had
    actually spent."""
    result = _tool_result()
    heavy = [
        ModelRequest(parts=[ToolReturnPart(tool_name="s", content=result, tool_call_id=str(i))])
        for i in range(10)
    ]
    body = message_chars(heavy)
    assert body.structured > 5_000
    assert body.prose == 0

    split = compose(30_000, TurnOverhead(system=500, tools=2_000), heavy)
    assert split is not None
    assert split.messages > split.tools
