"""Quant discovery — GGUF label extraction, repo listing, and the picker's route.

Hardware detection and the HuggingFace listing are stubbed so assertions don't depend on
the test host or the network.
"""

from __future__ import annotations

from services.cookbook.models import (
    Accelerator,
    AcceleratorKind,
    ComputeBackend,
    HardwareProfile,
    MemoryInfo,
    PlatformInfo,
)
from services.serving import hf
from services.serving.adapters.llamacpp import LlamaCppAdapter
from tests._helpers import client_app

_GB = 1024**3


def test_quant_label_extracts_common_gguf_quants():
    cases = {
        "Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf": "Q4_K_M",
        "qwen2.5-7b-instruct-q5_k_s.gguf": "Q5_K_S",
        "model.Q8_0.gguf": "Q8_0",
        "Llama-3.2-3B-Instruct-IQ4_XS.gguf": "IQ4_XS",
        "ggml-model-bf16.gguf": "BF16",
        "model-f16.gguf": "F16",
        "model-Q6_K.gguf": "Q6_K",
        "DeepSeek-R1-Distill-Qwen-7B-Q4_K_M-00001-of-00002.gguf": "Q4_K_M",
    }
    for name, expected in cases.items():
        assert hf.quant_label(name) == expected, name
    # No quant token present.
    assert hf.quant_label("tokenizer.json") is None
    assert hf.quant_label("model.gguf") is None


def test_list_gguf_quants_dedupes_filters_and_sorts(monkeypatch):
    files = [
        "README.md",
        "Model-Q5_K_M.gguf",
        "Model-Q4_K_M.gguf",
        "Model-Q4_K_M.gguf",  # duplicate quant
        "Model-Q8_0.gguf",
        "Model-f16.gguf",
        "config.json",
        "Model.gguf",  # no quant token → skipped
    ]

    class FakeHfApi:
        def __init__(self, token=None):
            pass

        def list_repo_files(self, repo):
            return files

    monkeypatch.setattr("huggingface_hub.HfApi", FakeHfApi)
    # Distinct, smallest-precision first.
    assert hf.list_gguf_quants("org/model") == ["Q4_K_M", "Q5_K_M", "Q8_0", "F16"]


def test_list_gguf_quants_degrades_to_empty_on_error(monkeypatch):
    class BoomHfApi:
        def __init__(self, token=None):
            pass

        def list_repo_files(self, repo):
            raise RuntimeError("network down")

    monkeypatch.setattr("huggingface_hub.HfApi", BoomHfApi)
    assert hf.list_gguf_quants("org/model") == []


def _fake_repo(monkeypatch, files):
    class FakeHfApi:
        def __init__(self, token=None):
            pass

        def list_repo_files(self, repo):
            return files

    monkeypatch.setattr("huggingface_hub.HfApi", FakeHfApi)


def test_gguf_filename_matches_quant_label_not_substring(monkeypatch):
    # "f16" is a substring of "bf16", and the BF16 file has the shorter name the old loose
    # match preferred — so a substring match would serve BF16 for an F16 request.
    _fake_repo(
        monkeypatch,
        ["some-long-prefix-F16.gguf", "BF16.gguf", "config.json"],
    )
    assert hf.gguf_filename("org/model", "F16") == "some-long-prefix-F16.gguf"
    assert hf.gguf_filename("org/model", "BF16") == "BF16.gguf"


def test_gguf_filename_prefers_base_over_shards_case_insensitively(monkeypatch):
    _fake_repo(
        monkeypatch,
        [
            "Model-Q4_K_M-00001-of-00002.gguf",
            "Model-Q4_K_M-00002-of-00002.gguf",
            "Model-Q4_K_M.gguf",  # base single-file — shortest, wins
        ],
    )
    assert hf.gguf_filename("org/model", "q4_k_m") == "Model-Q4_K_M.gguf"


def test_gguf_filename_degrades_to_default_for_unavailable_quant(monkeypatch):
    # A quant the repo doesn't offer (and a bare "Q4" that no exact label equals) falls back
    # to the engine's default pick — the shortest GGUF — never a different specific quant.
    files = ["Model-Q4_K_M.gguf", "Model-Q8_0.gguf"]
    _fake_repo(monkeypatch, files)
    assert hf.gguf_filename("org/model", "Q2_K") == min(files, key=len)
    assert hf.gguf_filename("org/model", "Q4") == min(files, key=len)


def test_gguf_filename_falls_back_to_substring_for_unrecognized_quant(monkeypatch):
    # A stored quant the label parser doesn't recognize (free-text from an older build, or
    # a quant family the matcher omits like ternary TQ1_0) must still resolve to a file
    # carrying it via a loose substring match — not silently serve the shortest default.
    _fake_repo(
        monkeypatch,
        ["short.gguf", "Model-TQ1_0.gguf", "Model-Q4_K_M.gguf"],
    )
    assert hf.gguf_filename("org/model", "TQ1_0") == "Model-TQ1_0.gguf"
    # Free-text "k_m" isn't a label, but substring-matches the K_M file (over the default).
    assert hf.gguf_filename("org/model", "k_m") == "Model-Q4_K_M.gguf"


def test_gguf_filename_unrecognized_quant_with_no_substring_match_degrades(monkeypatch):
    # An unrecognized quant that matches no filename still degrades to the default pick.
    files = ["Model-Q4_K_M.gguf", "Model-Q8_0.gguf"]
    _fake_repo(monkeypatch, files)
    assert hf.gguf_filename("org/model", "nonsense") == min(files, key=len)


def _apple_profile() -> HardwareProfile:
    return HardwareProfile(
        memory=MemoryInfo(total_bytes=128 * _GB, available_bytes=100 * _GB),
        accelerators=[
            Accelerator(
                name="Apple M3 Max",
                kind=AcceleratorKind.metal,
                vram_bytes=96 * _GB,
                unified=True,
            )
        ],
        compute_backend=ComputeBackend.metal,
        platform=PlatformInfo(system="Darwin", release="24", arch="arm64"),
    )


async def test_repo_quants_route(monkeypatch):
    async def fake_detect(self) -> HardwareProfile:
        return _apple_profile()

    monkeypatch.setattr("services.cookbook.service.CookbookService.detect", fake_detect)
    monkeypatch.setattr(
        LlamaCppAdapter, "list_quants", lambda self, repo, token=None: ["Q4_K_M", "Q8_0"]
    )

    async with client_app() as (client, _app):
        ok = await client.get(
            "/models/serving/repo-quants",
            params={"repo": "org/model", "engine": "llama.cpp"},
        )
        assert ok.status_code == 200
        assert ok.json() == ["Q4_K_M", "Q8_0"]

        # MLX bakes the quant into the repo id → no selectable quants.
        mlx = await client.get(
            "/models/serving/repo-quants",
            params={"repo": "mlx-community/x", "engine": "mlx"},
        )
        assert mlx.status_code == 200 and mlx.json() == []
