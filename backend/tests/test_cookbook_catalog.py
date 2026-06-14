"""Live-catalog parsing — against a fake httpx client returning canned HF/OpenRouter
JSON. No network. Covers base_model dedup, per-quant sizes, the OpenRouter capability
join, the HF heuristic fallback, and the degrade / serve-stale paths.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from core.exceptions import DegradedCapabilityError
from services.cookbook.catalog import ModelCatalog
from services.cookbook.sources import compute_quality

_QWEN_BASE = "Qwen/Qwen2.5-7B-Instruct"

# Two GGUF forks of the same base — should dedupe to one model keyed on the base, with
# the higher-download repo's file tree read for sizes.
_GGUF_LIST = [
    {
        "id": "bartowski/Qwen2.5-7B-Instruct-GGUF",
        "tags": [f"base_model:quantized:{_QWEN_BASE}", "license:apache-2.0", "gguf"],
        "downloads": 1000,
        "pipeline_tag": "text-generation",
        "gated": False,
        "gguf": {
            "total": 7_620_000_000,
            "context_length": 131072,
            "chat_template": "{%- if tools %}you can call tools{%- endif %}",
        },
    },
    {
        "id": "someone/Qwen2.5-7B-Instruct-GGUF",
        "tags": [f"base_model:quantized:{_QWEN_BASE}", "gguf"],
        "downloads": 500,
        "pipeline_tag": "text-generation",
        "gated": False,
        "gguf": {"total": 7_620_000_000, "context_length": 131072},
    },
]
_GGUF_TREE = [
    {"type": "file", "path": "Qwen2.5-7B-Instruct-Q4_K_M.gguf", "size": 4_700_000_000},
    {"type": "file", "path": "Qwen2.5-7B-Instruct-Q8_0.gguf", "size": 8_100_000_000},
    {"type": "file", "path": "README.md", "size": 1000},
]
_MLX_LIST = [
    {
        # A model NOT on the leaderboard → exercises the adoption fallback.
        "id": "mlx-community/Obscure-3B-Instruct-4bit",
        "tags": ["license:apache-2.0"],
        "downloads": 200,
        "pipeline_tag": "text-generation",
        "safetensors": {"total": 3_000_000_000},
        "gguf": {},
    }
]
_MLX_TREE = [{"type": "file", "path": "model.safetensors", "size": 4_300_000_000}]
# The base model's own repo — its real adoption/recency is the quality signal, not the
# quant fork's. Far higher than the bartowski quant repo's 1000 downloads.
_BASE_META = {"downloads": 5_000_000, "likes": 3000, "createdAt": "2026-05-01T00:00:00.000Z"}
_OPENROUTER = {
    "data": [
        {
            "hugging_face_id": _QWEN_BASE,
            "context_length": 131072,
            "architecture": {"input_modalities": ["text"]},
            "supported_parameters": ["tools", "reasoning"],
        }
    ]
}
# LMArena leaderboard rows (datasets-server shape). Joined by normalized name:
# "Qwen2.5-7B-Instruct" → "qwen257binstruct" == normalize(_QWEN_BASE).
_ARENA = {"rows": [{"row": {"Model": "Qwen2.5-7B-Instruct", "Arena Score": 1380}}]}


class _Resp:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


class _FakeClient:
    """Routes `get(url, params)` to canned payloads; an optional `fail` predicate makes
    matching calls raise, to exercise degrade/stale."""

    def __init__(self, *, openrouter=_OPENROUTER, arena=_ARENA, fail=lambda url: False):
        self._openrouter = openrouter
        self._arena = arena
        self._fail = fail

    async def get(self, url, params=None, headers=None, timeout=None):
        if self._fail(url):
            raise httpx.ConnectError("down")
        if "datasets-server" in url:  # the LMArena leaderboard (one page, then empty)
            return _Resp(self._arena if (params or {}).get("offset", 0) == 0 else {"rows": []})
        if url.endswith("/api/models"):
            is_mlx = any(key == "author" for key, _ in (params or []))
            return _Resp(_MLX_LIST if is_mlx else _GGUF_LIST)
        if "/tree/main" in url:
            return _Resp(_MLX_TREE if "mlx-community" in url else _GGUF_TREE)
        if "openrouter.ai" in url:
            return _Resp(self._openrouter)
        if "/api/models/" in url:  # base-model info (adoption fallback signals)
            return _Resp(_BASE_META)
        return _Resp([])


async def test_catalog_builds_dedupes_and_enriches():
    catalog = await ModelCatalog(_FakeClient(), list_limit=20, max_models=10).get()
    ids = {m.id for m in catalog}
    assert _QWEN_BASE in ids  # both GGUF forks collapsed onto the base
    assert "mlx-community/Obscure-3B-Instruct-4bit" in ids

    qwen = next(m for m in catalog if m.id == _QWEN_BASE)
    assert qwen.params_b == 7.62
    assert qwen.context_default == 131072
    assert qwen.license == "apache-2.0"
    # Exact per-quant sizes from the (higher-download) repo's file tree.
    quants = {q.label: q.size_bytes for q in qwen.quants}
    assert quants == {"Q4_K_M": 4_700_000_000, "Q8_0": 8_100_000_000}
    # OpenRouter join (exact hugging_face_id) sets capabilities.
    assert qwen.capabilities.tools and qwen.capabilities.thinking
    assert not qwen.capabilities.vision
    # Adoption signals come from the BASE model's repo, not the quant fork (1000 dl).
    assert qwen.downloads == 5_000_000
    assert qwen.likes == 3000
    # Quality is the Arena Elo (fuzzy-joined), landing in the benchmarked upper half.
    assert qwen.arena_elo == 1380
    assert qwen.quality_score > 0.5

    # The MLX model isn't on the leaderboard → no Elo, adoption-tier quality (≤ 0.5).
    mlx = next(m for m in catalog if m.id.startswith("mlx-community/"))
    assert mlx.arena_elo is None
    assert mlx.quality_score <= 0.5


def test_quality_tiers():
    now = datetime(2026, 6, 14, tzinfo=UTC)
    # Own Elo (proven) > family-rated new release > popular-but-unknown > obscure.
    benchmarked = compute_quality(1350, None, "2023-01-01T00:00:00.000Z", 200, 2, now=now)
    family_new = compute_quality(None, 1340, "2026-05-01T00:00:00.000Z", 1_000, 50, now=now)
    popular = compute_quality(None, None, "2026-05-01T00:00:00.000Z", 5_000_000, 3000, now=now)
    obscure = compute_quality(None, None, "2023-01-01T00:00:00.000Z", 200, 2, now=now)
    assert benchmarked > family_new > popular > obscure >= 0.0
    # A new model whose family is benchmarked clears the adoption ceiling — so the latest
    # Gemma/Qwen rank with their lineage, above any unknown-lineage model however popular.
    assert family_new > 0.35 >= popular


async def test_capabilities_fall_back_to_hf_when_openrouter_misses():
    # OpenRouter returns nothing → tools come from the GGUF chat-template heuristic.
    catalog = await ModelCatalog(_FakeClient(openrouter={"data": []})).get()
    qwen = next(m for m in catalog if m.id == _QWEN_BASE)
    assert qwen.capabilities.tools  # "{%- if tools %}" in the chat template


async def test_openrouter_failure_still_builds_the_catalog():
    client = _FakeClient(fail=lambda url: "openrouter.ai" in url)
    catalog = await ModelCatalog(client).get()
    assert any(m.id == _QWEN_BASE for m in catalog)  # HF spine unaffected


async def test_degrades_when_hf_unreachable_and_no_cache():
    client = _FakeClient(fail=lambda url: "huggingface.co" in url)
    with pytest.raises(DegradedCapabilityError):
        await ModelCatalog(client).get()


async def test_serves_stale_when_a_refresh_fails():
    state = {"down": False}
    client = _FakeClient(fail=lambda url: state["down"])
    catalog = ModelCatalog(client, ttl_s=0.0)  # ttl 0 ⇒ every get re-fetches
    first = await catalog.get()
    assert first
    state["down"] = True
    second = await catalog.get()  # refresh fails, but a cached copy exists
    assert [m.id for m in second] == [m.id for m in first]
