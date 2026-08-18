"""MlxAdapter — the pure, runtime-free bits (no mlx-vlm install / network needed).

Covers ``serve_spec`` argv shape, ``resolved_model_id``, capability flags, and the
Apple-Silicon gating in ``is_available``. ``ensure_engine``/``download_spec`` (which would
create a venv or hit HuggingFace) are deliberately not exercised here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from services.serving.adapters.mlx import MlxAdapter
from services.serving.models import EngineKind, Workload
from services.serving.paths import ServingPaths


def _adapter(tmp_path: Path) -> MlxAdapter:
    return MlxAdapter(ServingPaths(tmp_path))


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
    from core.exceptions import ServingError

    adapter = _adapter(tmp_path)
    with pytest.raises(ServingError):
        adapter.serve_spec(tmp_path / "snap", 8000, Workload.chat, "mlx-community/x")


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
