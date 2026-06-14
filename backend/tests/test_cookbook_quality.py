"""Quality-source adapters + the hardened join — against canned payloads, no network.

Covers each adapter's parse into ``{normalize_name: ModelQuality}``, the keyless-source
short-circuit, the source-selection fallback, and the join-coverage guard: the HF repo
id, the LMArena name, and the Artificial Analysis name for one model must all normalize
to the *same* key (the lossy join was why most models never matched a score).
"""

from __future__ import annotations

from services.cookbook.quality import (
    ArtificialAnalysisSource,
    LlmStatsSource,
    LMArenaSource,
    build_quality_source,
)
from services.cookbook.sources import normalize_name


class _Resp:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


class _FakeClient:
    """Returns one canned payload for every GET (the adapter under test makes one call)."""

    def __init__(self, payload):
        self._payload = payload
        self.calls: list[dict] = []

    async def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "headers": headers or {}})
        return _Resp(self._payload)


async def test_lmarena_parses_elo_and_normalizes_into_band():
    payload = {"rows": [{"row": {"Model": "Qwen3.6-32B-Instruct", "Arena Score": 1350}}]}
    # One page then empty, so the paginating loop terminates.
    client = _FakeClient(payload)

    async def get(url, params=None, headers=None, timeout=None):
        return _Resp(payload if (params or {}).get("offset", 0) == 0 else {"rows": []})

    client.get = get  # type: ignore[method-assign]
    scores = await LMArenaSource(client).scores()
    q = scores[normalize_name("Qwen3.6-32B-Instruct")]
    assert q.metric == "ELO"
    assert q.display == 1350
    assert 0.8 < q.score < 0.9  # (1350-1100)/300 ≈ 0.83


async def test_artificial_analysis_parses_index_and_needs_a_key():
    payload = {
        "data": [
            {
                "name": "Qwen3.6 32B",
                "slug": "qwen3-6-32b",
                "evaluations": {
                    "artificial_analysis_intelligence_index": 55.0,
                    "artificial_analysis_coding_index": 60.0,
                },
            }
        ]
    }
    scores = await ArtificialAnalysisSource(_FakeClient(payload), api_key="k").scores()
    q = scores[normalize_name("Qwen3.6 32B")]
    assert q.metric == "INTELLIGENCE"
    assert q.display == 55.0
    assert abs(q.score - 0.55) < 1e-9
    assert q.coding == 60.0
    # No key → no call, empty map (degrades to the next tier).
    assert await ArtificialAnalysisSource(_FakeClient(payload), api_key="").scores() == {}


async def test_llm_stats_defensive_parse_and_needs_a_key():
    payload = {"data": [{"name": "Qwen3.6-32B", "score": 72}]}
    scores = await LlmStatsSource(_FakeClient(payload), api_key="k").scores()
    q = scores[normalize_name("Qwen3.6-32B")]
    assert q.metric == "SCORE"
    assert q.display == 72.0
    assert abs(q.score - 0.72) < 1e-9  # 0..100 native scale → 0..1
    assert await LlmStatsSource(_FakeClient(payload), api_key=None).scores() == {}


def test_hardened_join_collapses_role_and_quant_suffixes():
    # The HF repo id, the leaderboard name, and the AA display name for one model must
    # all land on the same key — the whole point of the join hardening.
    key = normalize_name("Qwen/Qwen3.6-32B-Instruct")
    assert key == "qwen3632b"
    assert normalize_name("Qwen3.6 32B") == key
    assert normalize_name("Qwen3.6-32B-4bit") == key
    assert normalize_name("qwen3.6-32b-chat") == key


def test_source_selection_falls_back_to_lmarena_without_a_key():
    client = _FakeClient({})
    aa = build_quality_source(client, "artificial_analysis", aa_api_key="k")
    assert aa.name == "artificial_analysis"
    assert build_quality_source(client, "llm_stats", llm_stats_api_key="k").name == "llm_stats"
    # Chosen source but no key → keyless LMArena, so ranking still works with zero setup.
    assert build_quality_source(client, "artificial_analysis").name == "lmarena"
    assert build_quality_source(client, "lmarena").name == "lmarena"
    assert build_quality_source(client, "bogus").name == "lmarena"
