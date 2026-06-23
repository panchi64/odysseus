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


def _apple_profile() -> HardwareProfile:
    return HardwareProfile(
        memory=MemoryInfo(total_bytes=128 * _GB, available_bytes=100 * _GB),
        accelerators=[
            Accelerator(
                name="Apple M3 Max", kind=AcceleratorKind.metal,
                vram_bytes=96 * _GB, unified=True,
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
