"""The context-window fullness derivation — the single owner of the fraction and
severity thresholds (events.ContextWindow), shared by live run metrics and the
on-load conversation detail."""

from __future__ import annotations

import pytest
from pydantic_ai import ModelRequest, ModelResponse
from pydantic_ai.messages import TextPart, UserPromptPart
from pydantic_ai.usage import RequestUsage

from runs import ContextWindow
from runs.events import RunMetrics
from services.conversations import context_footprint


def _response(input_tokens: int, output_tokens: int) -> ModelResponse:
    return ModelResponse(
        parts=[TextPart(content="x")],
        usage=RequestUsage(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def test_footprint_is_last_response_not_a_sum():
    # A tool-calling / multi-turn run holds several responses; each later request
    # re-sends the growing history, so its input count already subsumes the prior.
    # The footprint must be the LAST response's prompt+generation, never the sum —
    # summing would overstate fullness several-fold (the bug this guards).
    messages = [
        ModelRequest(parts=[UserPromptPart(content="hi")]),
        _response(50, 5),
        ModelRequest(parts=[UserPromptPart(content="tool result")]),
        _response(140, 12),
    ]
    assert context_footprint(messages) == 152  # last response only, not 50+5+140+12


def test_footprint_none_without_response():
    assert context_footprint([ModelRequest(parts=[UserPromptPart(content="hi")])]) is None


def test_footprint_none_when_usage_unreported():
    # Local servers often report 0 input — treated as unmeasured, not a real 0.
    assert context_footprint([_response(0, 0)]) is None


def test_from_used_computes_fraction():
    state = ContextWindow.from_used(160_000, 200_000)
    assert state is not None
    assert state.used == 160_000
    assert state.window == 200_000
    assert state.fraction == pytest.approx(0.8)


@pytest.mark.parametrize(
    ("used", "expected"),
    [
        (100_000, "nominal"),
        (149_999, "nominal"),
        (150_000, "warn"),
        (179_999, "warn"),
        (180_000, "alert"),
    ],
)
def test_level_thresholds(used: int, expected: str):
    # 75% (150k) flips nominal→warn; 90% (180k) flips warn→alert, against a 200k window.
    state = ContextWindow.from_used(used, 200_000)
    assert state is not None
    assert state.level == expected


def test_fraction_clamps_when_over_full():
    state = ContextWindow.from_used(250_000, 200_000)
    assert state is not None
    assert state.fraction == 1.0
    assert state.level == "alert"


def test_none_without_window():
    assert ContextWindow.from_used(1_000, None) is None
    assert ContextWindow.from_used(1_000, 0) is None


def test_none_without_footprint():
    assert ContextWindow.from_used(None, 200_000) is None


def test_run_metrics_exposes_context_on_the_wire():
    # context_used is the last-response footprint, deliberately distinct from the
    # cumulative input/output token totals on the same frame.
    metrics = RunMetrics(
        input_tokens=999_999, output_tokens=999_999, context_used=195_000, context_window=200_000
    )
    payload = metrics.model_dump(mode="json")
    assert payload["context"] == {
        "used": 195_000,
        "window": 200_000,
        "fraction": pytest.approx(0.975),
        "level": "alert",
    }


def test_run_metrics_context_null_without_window():
    payload = RunMetrics(context_used=100, output_tokens=5).model_dump(mode="json")
    assert payload["context"] is None


def test_run_metrics_context_null_without_footprint():
    # Cumulative totals present but no measured footprint → still null.
    payload = RunMetrics(input_tokens=500, output_tokens=20, context_window=200_000).model_dump(
        mode="json"
    )
    assert payload["context"] is None
