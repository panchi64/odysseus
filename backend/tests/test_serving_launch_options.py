"""Per-model engine launch overrides — validation, argv composition, and persistence.

The load-bearing property under test is **absent means absent**: an unset field emits no
flag, so llama.cpp's own auto-sizing (server slots, GPU layers, flash attention, continuous
batching, prompt caching) survives untouched. A regression here would look like a working
server that quietly performs worse than the one it replaced.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from core.exceptions import ServingError
from models.serving import ManagedModel
from services.serving.adapters.llamacpp import LlamaCppAdapter
from services.serving.models import (
    EngineKind,
    KvCacheType,
    LaunchOptions,
    Workload,
    validate_extra_args,
    validate_options,
)
from services.serving.paths import ServingPaths
from services.serving.store import launch_options

# --- extra-arg validation ---------------------------------------------------


@pytest.mark.parametrize(
    "flag",
    ["-c", "--ctx-size", "-ctk", "--cache-type-k", "-ctv", "--cache-type-v", "--cache-reuse"],
)
def test_flags_owned_by_the_curated_fields_are_rejected(flag):
    with pytest.raises(ServingError, match="fields above"):
        validate_extra_args([flag, "4096"])


@pytest.mark.parametrize(
    "flag", ["-m", "--model", "--host", "--port", "--alias", "--jinja", "--embeddings"]
)
def test_flags_owned_by_the_platform_are_rejected(flag):
    # --host is the one that matters beyond tidiness: 0.0.0.0 would put the model server
    # on the network, outside the loopback assumption the rest of serving is built on.
    with pytest.raises(ServingError, match="managed by the platform"):
        validate_extra_args([flag, "0.0.0.0"])


def test_equals_form_is_caught_too():
    with pytest.raises(ServingError):
        validate_extra_args(["--ctx-size=8192"])


def test_unrelated_flags_pass():
    validate_extra_args(["--no-context-shift", "--cache-ram", "16384", "-fa", "on"])


# --- per-engine gating ------------------------------------------------------


def test_an_engine_that_cannot_use_options_rejects_them():
    # MLX's adapter ignores LaunchOptions entirely. Storing them would leave the row
    # carrying tuning that never reaches a process while the UI renders it as applied.
    with pytest.raises(ServingError, match="no tunable launch options"):
        validate_options(EngineKind.mlx, LaunchOptions(context_size=4096))


def test_empty_options_are_accepted_by_any_engine():
    validate_options(EngineKind.mlx, LaunchOptions())
    validate_options(EngineKind.mlx, None)


def test_the_tunable_engine_still_gets_its_extra_args_validated():
    validate_options(EngineKind.llama_cpp, LaunchOptions(context_size=4096))
    with pytest.raises(ServingError, match="managed by the platform"):
        validate_options(EngineKind.llama_cpp, LaunchOptions(extra_args=["--host", "0.0.0.0"]))


# --- argv composition -------------------------------------------------------


def _adapter(tmp_path: Path) -> LlamaCppAdapter:
    adapter = LlamaCppAdapter(ServingPaths(tmp_path))
    adapter._binary = str(tmp_path / "llama-server")
    (tmp_path / "llama-server").write_text("")
    return adapter


def _argv(tmp_path: Path, options: LaunchOptions | None, workload=Workload.chat) -> list[str]:
    spec = _adapter(tmp_path).serve_spec(
        Path("/models/m.gguf"), 8080, workload, "acme/model", options
    )
    return spec.argv


def test_empty_options_emit_no_extra_flags(tmp_path):
    # The regression guard: tuning fields left blank must produce exactly the argv that
    # shipped before this feature existed.
    assert _argv(tmp_path, LaunchOptions()) == _argv(tmp_path, None)
    argv = _argv(tmp_path, LaunchOptions())
    for flag in ("-c", "-ctk", "-ctv", "--cache-reuse", "-np", "--parallel", "-ngl"):
        assert flag not in argv


def test_curated_fields_map_to_their_flags(tmp_path):
    argv = _argv(
        tmp_path,
        LaunchOptions(context_size=32768, kv_cache_type=KvCacheType.q8_0, cache_reuse=256),
    )
    assert argv[argv.index("-c") + 1] == "32768"
    assert argv[argv.index("--cache-reuse") + 1] == "256"
    # Both halves of the cache are quantized together.
    assert argv[argv.index("-ctk") + 1] == "q8_0"
    assert argv[argv.index("-ctv") + 1] == "q8_0"


def test_extra_args_precede_the_flags_the_adapter_owns(tmp_path):
    # Ordering is the belt to validation's braces: llama.cpp takes the last occurrence, so
    # placing operator args first means identity and loopback binding always win.
    argv = _argv(tmp_path, LaunchOptions(extra_args=["--no-context-shift"]))
    assert argv.index("--no-context-shift") < argv.index("--host")
    assert argv.index("--no-context-shift") < argv.index("--alias")


def test_embedding_workload_keeps_its_flag_alongside_options(tmp_path):
    argv = _argv(tmp_path, LaunchOptions(context_size=512), workload=Workload.embedding)
    assert "--embeddings" in argv and argv[argv.index("-c") + 1] == "512"


# --- context-window probe ---------------------------------------------------


def _stub_props(monkeypatch, *, status: int = 200, payload: dict | None = None) -> None:
    """Answer the adapter's /props call. The request must be attached to the response —
    `raise_for_status` needs it, and a bare Response would fail for the wrong reason."""

    async def fake_get(self, url, **kwargs):
        return httpx.Response(status, json=payload or {}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)


async def test_probe_reads_the_per_slot_n_ctx_from_props(tmp_path, monkeypatch):
    # The shape llama-server actually serves: the per-slot context lives under
    # `default_generation_settings`, not at the top level.
    _stub_props(
        monkeypatch,
        payload={"default_generation_settings": {"n_ctx": 8192}, "total_slots": 4},
    )
    assert await _adapter(tmp_path).probe_context_window(8080) == 8192


async def test_probe_falls_back_to_a_top_level_n_ctx(tmp_path, monkeypatch):
    _stub_props(monkeypatch, payload={"n_ctx": 8192, "total_slots": 4})
    assert await _adapter(tmp_path).probe_context_window(8080) == 8192


@pytest.mark.parametrize(
    "payload",
    [{"n_ctx": 0}, {"n_ctx": "big"}, {}, {"default_generation_settings": {"n_ctx": 0}}],
)
async def test_probe_declines_on_an_unusable_n_ctx(tmp_path, monkeypatch, payload):
    _stub_props(monkeypatch, payload=payload)
    assert await _adapter(tmp_path).probe_context_window(8080) is None


async def test_probe_declines_on_an_error_status(tmp_path, monkeypatch):
    _stub_props(monkeypatch, status=404, payload={"n_ctx": 8192})
    assert await _adapter(tmp_path).probe_context_window(8080) is None


async def test_probe_degrades_to_none_when_the_server_is_unreachable(tmp_path, monkeypatch):
    async def fake_get(self, url, **kwargs):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    assert await _adapter(tmp_path).probe_context_window(8080) is None


# --- persistence ------------------------------------------------------------


def test_unreadable_stored_options_degrade_to_defaults():
    # Degrade, don't crash: a blob this build can't parse must not sink the status list.
    row = ManagedModel(
        owner_id="o", engine="llama.cpp", workload="chat", hf_repo="acme/m",
        launch_options={"context_size": "not-a-number"},
    )
    assert launch_options(row) == LaunchOptions()


def test_stored_options_round_trip():
    row = ManagedModel(
        owner_id="o", engine="llama.cpp", workload="chat", hf_repo="acme/m",
        launch_options=LaunchOptions(context_size=4096, cache_reuse=128).model_dump(mode="json"),
    )
    assert launch_options(row).context_size == 4096
    assert launch_options(row).cache_reuse == 128
