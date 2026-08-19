"""MlxAdapter — the pure, runtime-free bits (no mlx-vlm install / network needed).

Covers ``serve_spec`` argv shape (including how launch options translate into mlx-vlm's
flag vocabulary and how extra arguments override them), the ``/health`` probes that give
the endpoint its real context window and honest tool-calling flag, vision detection from
the snapshot's own config, artifact validation, and the Apple-Silicon gating in
``is_available``. ``ensure_engine``/``download_spec`` (which would create a venv or hit
HuggingFace) are deliberately not exercised here.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from core.exceptions import ServingError
from services.serving.adapters.base import EngineAdapter
from services.serving.adapters.mlx import MlxAdapter
from services.serving.models import EngineKind, KvCacheType, LaunchOptions, Workload
from services.serving.paths import ServingPaths


def _adapter(tmp_path: Path) -> MlxAdapter:
    return MlxAdapter(ServingPaths(tmp_path))


def _ready(tmp_path: Path) -> MlxAdapter:
    adapter = _adapter(tmp_path)
    adapter._script = str(tmp_path / "venv" / "bin" / "mlx_vlm.server")
    return adapter


def _argv(tmp_path: Path, options: LaunchOptions | None = None) -> list[str]:
    adapter = _ready(tmp_path)
    snapshot = tmp_path / "snap"
    return adapter.serve_spec(snapshot, 8123, Workload.chat, str(snapshot), options).argv


def _stub_health(monkeypatch, *, status: int = 200, payload=None) -> None:
    """Answer the adapter's /health call. The request must be attached to the response —
    `raise_for_status` needs it, and a bare Response would fail for the wrong reason."""

    async def fake_get(self, url, **kwargs):
        return httpx.Response(status, json=payload, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)


def _snapshot(tmp_path: Path, config: dict | None) -> Path:
    """A minimally-shaped MLX snapshot dir — what `validate_artifact` looks for."""
    snap = tmp_path / "snap"
    snap.mkdir(exist_ok=True)
    (snap / "model.safetensors").write_bytes(b"")
    if config is not None:
        (snap / "config.json").write_text(json.dumps(config))
    return snap


def test_capabilities_cover_chat_and_vision_with_native_tools(tmp_path: Path):
    adapter = _adapter(tmp_path)
    assert adapter.kind == EngineKind.mlx
    assert adapter.workloads == frozenset({Workload.chat, Workload.vision})
    # Embeddings stay on llama.cpp for one uniform GGUF embedding stack, even though
    # mlx-vlm exposes an embeddings route.
    assert Workload.embedding not in adapter.workloads
    assert adapter.native_tools_default is True
    assert adapter.context_window_hint and adapter.context_window_hint > 0


def test_serve_spec_carries_model_path_host_and_port(tmp_path: Path):
    adapter = _adapter(tmp_path)
    adapter._script = str(tmp_path / "venv" / "bin" / "mlx_vlm.server")
    snapshot = tmp_path / "models" / "mlx" / "mlx-community__Qwen2.5-7B-Instruct-4bit"
    model_id = str(snapshot)

    spec = adapter.serve_spec(snapshot, 8123, Workload.chat, model_id)
    argv = spec.argv

    assert argv[0] == adapter._script
    # The local snapshot dir is pre-loaded at startup, so readiness means weights resident.
    assert argv[argv.index("--model") + 1] == str(snapshot)
    # Loopback-bound on the allocated port (mlx-vlm would default to 0.0.0.0).
    assert argv[argv.index("--host") + 1] == "127.0.0.1"
    assert argv[argv.index("--port") + 1] == "8123"


def test_serve_spec_is_the_same_argv_for_vision(tmp_path: Path):
    """mlx-vlm is a VLM server first — a vision model launches identically; the workload
    only decides how the endpoint is advertised."""
    adapter = _adapter(tmp_path)
    adapter._script = str(tmp_path / "venv" / "bin" / "mlx_vlm.server")
    snapshot = tmp_path / "snap"

    chat = adapter.serve_spec(snapshot, 8123, Workload.chat, str(snapshot))
    vision = adapter.serve_spec(snapshot, 8123, Workload.vision, str(snapshot))
    assert chat.argv == vision.argv


def test_serve_spec_without_ensure_engine_raises(tmp_path: Path):
    adapter = _adapter(tmp_path)
    with pytest.raises(ServingError):
        adapter.serve_spec(tmp_path / "snap", 8000, Workload.chat, "mlx-community/x")


# --- launch options → mlx-vlm's flag vocabulary -----------------------------


def test_empty_options_emit_no_tuning_flags(tmp_path: Path):
    # Absent means absent: a blank form must produce exactly the argv that shipped before
    # tuning existed, so mlx-vlm's own defaults stand.
    assert _argv(tmp_path, LaunchOptions()) == _argv(tmp_path, None)
    for flag in ("--max-kv-size", "--kv-bits"):
        assert flag not in _argv(tmp_path, LaunchOptions())


def test_context_size_becomes_the_kv_size_bound(tmp_path: Path):
    # mlx-vlm has no total-context flag; bounding the KV cache is the same thing from the
    # operator's side — the tokens one request may hold.
    argv = _argv(tmp_path, LaunchOptions(context_size=8192))
    assert argv[argv.index("--max-kv-size") + 1] == "8192"


@pytest.mark.parametrize(("kind", "bits"), [(KvCacheType.q8_0, "8"), (KvCacheType.q4_0, "4")])
def test_kv_cache_precision_becomes_a_bit_width(tmp_path: Path, kind, bits):
    argv = _argv(tmp_path, LaunchOptions(kv_cache_type=kind))
    assert argv[argv.index("--kv-bits") + 1] == bits


def test_f16_is_the_unquantized_default_and_emits_nothing(tmp_path: Path):
    assert "--kv-bits" not in _argv(tmp_path, LaunchOptions(kv_cache_type=KvCacheType.f16))


def test_extra_args_are_appended(tmp_path: Path):
    argv = _argv(tmp_path, LaunchOptions(extra_args=["--max-tokens", "2048"]))
    assert argv[-2:] == ["--max-tokens", "2048"]


def test_an_extra_arg_overrides_the_field_it_names(tmp_path: Path):
    # The flag reaches the engine once, carrying the operator's value — not twice, leaving
    # argparse's last-wins rule to decide what they meant.
    argv = _argv(
        tmp_path,
        LaunchOptions(context_size=8192, extra_args=["--max-kv-size", "4096"]),
    )
    assert argv.count("--max-kv-size") == 1
    assert argv[argv.index("--max-kv-size") + 1] == "4096"


def test_the_flags_the_adapter_owns_survive_extra_args(tmp_path: Path):
    argv = _argv(tmp_path, LaunchOptions(extra_args=["--trust-remote-code"]))
    for flag in ("--model", "--host", "--port"):
        assert flag in argv


def test_mlx_allows_a_longer_startup_than_the_shared_default(tmp_path: Path):
    # mlx-vlm loads the whole model inside its lifespan, before uvicorn binds the port —
    # so a large model's entire load has to fit inside this budget.
    assert _adapter(tmp_path).startup_timeout_s > EngineAdapter.startup_timeout_s


# --- /health probes ---------------------------------------------------------


async def test_context_window_prefers_the_effective_limit(tmp_path: Path, monkeypatch):
    # `effective_context_limit` already folds a --max-kv-size cap into the model's own
    # declared window, so it beats both of the others when present.
    _stub_health(
        monkeypatch,
        payload={
            "effective_context_limit": 8192,
            "loaded_context_size": 131072,
            "configured_context_limit": 16384,
        },
    )
    assert await _adapter(tmp_path).probe_context_window(8123) == 8192


async def test_context_window_falls_back_through_the_other_keys(tmp_path: Path, monkeypatch):
    _stub_health(monkeypatch, payload={"loaded_context_size": 32768})
    assert await _adapter(tmp_path).probe_context_window(8123) == 32768
    _stub_health(monkeypatch, payload={"configured_context_limit": 4096})
    assert await _adapter(tmp_path).probe_context_window(8123) == 4096


@pytest.mark.parametrize(
    "payload",
    [
        {"effective_context_limit": 0},
        {"effective_context_limit": True},  # a bool is an int; it isn't a window
        {"effective_context_limit": "big"},
        {},
        ["not", "a", "dict"],
        None,
    ],
)
async def test_context_window_declines_on_an_unusable_payload(
    tmp_path: Path, monkeypatch, payload
):
    _stub_health(monkeypatch, payload=payload)
    assert await _adapter(tmp_path).probe_context_window(8123) is None


async def test_probes_degrade_when_the_server_is_unreachable(tmp_path: Path, monkeypatch):
    async def fake_get(self, url, **kwargs):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    adapter = _adapter(tmp_path)
    assert await adapter.probe_context_window(8123) is None
    # An unreachable server must not silently break a role binding that already worked.
    assert await adapter.probe_native_tools(8123) is adapter.native_tools_default


async def test_native_tools_follows_the_loaded_tool_parser(tmp_path: Path, monkeypatch):
    _stub_health(monkeypatch, payload={"loaded_tool_parser": "hermes"})
    assert await _adapter(tmp_path).probe_native_tools(8123) is True


async def test_native_tools_is_false_when_the_template_has_no_parser(
    tmp_path: Path, monkeypatch
):
    # The case worth catching: the model loads and chats fine, but no request would ever
    # produce a tool call — so a chat role must refuse it rather than degrade silently.
    _stub_health(monkeypatch, payload={"loaded_tool_parser": None})
    assert await _adapter(tmp_path).probe_native_tools(8123) is False


@pytest.mark.parametrize("payload", [{"status": "healthy"}, {}, ["nope"], None])
async def test_native_tools_keeps_the_default_when_the_key_is_absent(
    tmp_path: Path, monkeypatch, payload
):
    _stub_health(monkeypatch, payload=payload)
    adapter = _adapter(tmp_path)
    assert await adapter.probe_native_tools(8123) is adapter.native_tools_default


async def test_probes_decline_on_an_error_status(tmp_path: Path, monkeypatch):
    _stub_health(monkeypatch, status=500, payload={"effective_context_limit": 8192})
    assert await _adapter(tmp_path).probe_context_window(8123) is None


# --- vision detection -------------------------------------------------------


def test_vision_is_read_from_the_snapshot_config(tmp_path: Path):
    # mlx-vlm serves text-only and multimodal checkpoints through an identical launch, so
    # the declared workload can't tell them apart — the config can.
    snap = _snapshot(tmp_path, {"model_type": "qwen2_5_vl", "vision_config": {"depth": 32}})
    assert _adapter(tmp_path).detect_vision(snap, Workload.chat) is True


def test_a_text_only_checkpoint_is_not_vision(tmp_path: Path):
    snap = _snapshot(tmp_path, {"model_type": "qwen3"})
    assert _adapter(tmp_path).detect_vision(snap, Workload.chat) is False


@pytest.mark.parametrize("config", [None, {"vision_config": {}}])
def test_vision_declines_on_a_missing_or_empty_config(tmp_path: Path, config):
    snap = _snapshot(tmp_path, config)
    assert _adapter(tmp_path).detect_vision(snap, Workload.chat) is False


def test_vision_declines_on_malformed_json(tmp_path: Path):
    snap = _snapshot(tmp_path, None)
    (snap / "config.json").write_text("{not json")
    assert _adapter(tmp_path).detect_vision(snap, Workload.chat) is False


def test_a_declared_vision_workload_still_wins(tmp_path: Path):
    snap = _snapshot(tmp_path, {"model_type": "qwen3"})
    assert _adapter(tmp_path).detect_vision(snap, Workload.vision) is True


# --- artifact validation (importing weights already on disk) ----------------


def test_a_well_shaped_snapshot_validates(tmp_path: Path):
    _adapter(tmp_path).validate_artifact(_snapshot(tmp_path, {"model_type": "qwen3"}))


def test_a_file_is_refused_with_what_was_expected(tmp_path: Path):
    gguf = tmp_path / "model.gguf"
    gguf.write_bytes(b"")
    with pytest.raises(ServingError, match="model folder"):
        _adapter(tmp_path).validate_artifact(gguf)


def test_a_folder_without_a_config_is_refused(tmp_path: Path):
    snap = _snapshot(tmp_path, None)
    with pytest.raises(ServingError, match="config.json"):
        _adapter(tmp_path).validate_artifact(snap)


def test_a_folder_without_weights_is_refused(tmp_path: Path):
    snap = _snapshot(tmp_path, {"model_type": "qwen3"})
    (snap / "model.safetensors").unlink()
    with pytest.raises(ServingError, match="safetensors"):
        _adapter(tmp_path).validate_artifact(snap)


def test_a_missing_path_is_refused(tmp_path: Path):
    with pytest.raises(ServingError, match="nothing at"):
        _adapter(tmp_path).validate_artifact(tmp_path / "nowhere")


def test_resolved_model_id_is_the_local_snapshot_path(tmp_path: Path):
    """mlx-vlm has no --served-model-name: it keys a model by the path it loaded from and
    resolves a request's `model` the same way, so the served id is the snapshot path."""
    adapter = _adapter(tmp_path)
    repo = "mlx-community/Meta-Llama-3.1-8B-Instruct-4bit"
    snapshot = tmp_path / "snap"
    assert adapter.resolved_model_id(repo, snapshot) == str(snapshot)


@pytest.mark.parametrize(
    ("system", "machine", "expected"),
    [
        ("Darwin", "arm64", True),
        ("Darwin", "x86_64", False),
        ("Linux", "x86_64", False),
        ("Linux", "aarch64", False),
        ("Windows", "AMD64", False),
    ],
)
async def test_is_available_only_on_apple_silicon(
    monkeypatch, tmp_path: Path, system: str, machine: str, expected: bool
):
    monkeypatch.setattr("services.serving.adapters.mlx.platform.system", lambda: system)
    monkeypatch.setattr("services.serving.adapters.mlx.platform.machine", lambda: machine)
    assert await _adapter(tmp_path).is_available() is expected


# --- the engine venv --------------------------------------------------------


def test_the_venv_installs_jinja2_alongside_mlx_vlm(tmp_path: Path, monkeypatch):
    """mlx-vlm doesn't declare jinja2, but every chat request renders the model's chat
    template through it. Without it the server starts, reports healthy, and answers
    /v1/models — then fails *every* completion. Nothing in the startup path catches that,
    so the requirement list is where it has to be guaranteed."""
    calls: list[list[str]] = []
    monkeypatch.setattr(MlxAdapter, "_uv", lambda self, args: calls.append(args))
    monkeypatch.setattr(Path, "is_file", lambda self: True)

    _adapter(tmp_path)._install()

    install = next(a for a in calls if a[:2] == ["pip", "install"])
    assert any(a.startswith("mlx-vlm==") for a in install)
    assert "jinja2" in install
