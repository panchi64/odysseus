"""MlxAdapter — the pure, runtime-free bits (no mlx-openai-server / network needed).

Covers ``serve_spec`` argv shape, ``resolved_model_id``, capability flags, and the
Apple-Silicon gating in ``is_available``. ``ensure_engine``/``download_run`` (which would
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


def test_capabilities_are_chat_only_with_native_tools(tmp_path: Path):
    adapter = _adapter(tmp_path)
    assert adapter.kind == EngineKind.mlx
    assert adapter.workloads == frozenset({Workload.chat})
    assert Workload.embedding not in adapter.workloads
    assert adapter.native_tools_default is True
    assert adapter.context_window_hint and adapter.context_window_hint > 0


def test_serve_spec_carries_model_path_host_and_port(tmp_path: Path):
    adapter = _adapter(tmp_path)
    adapter._script = str(tmp_path / "venv" / "bin" / "mlx-openai-server")
    snapshot = tmp_path / "models" / "mlx" / "mlx-community__Qwen2.5-7B-Instruct-4bit"
    model_id = "mlx-community/Qwen2.5-7B-Instruct-4bit"

    spec = adapter.serve_spec(snapshot, 8123, Workload.chat, model_id)
    argv = spec.argv

    assert argv[0] == adapter._script
    assert "launch" in argv
    # The local snapshot dir is passed as the model path.
    assert "--model-path" in argv
    assert argv[argv.index("--model-path") + 1] == str(snapshot)
    # Loopback-bound on the allocated port.
    assert argv[argv.index("--host") + 1] == "127.0.0.1"
    assert argv[argv.index("--port") + 1] == "8123"
    # Launched as a language (chat) model, aliased so request `model` matches.
    assert argv[argv.index("--model-type") + 1] == "lm"
    assert argv[argv.index("--served-model-name") + 1] == model_id


def test_serve_spec_without_ensure_engine_raises(tmp_path: Path):
    from core.exceptions import ServingError

    adapter = _adapter(tmp_path)
    with pytest.raises(ServingError):
        adapter.serve_spec(tmp_path / "snap", 8000, Workload.chat, "mlx-community/x")


def test_resolved_model_id_is_the_repo(tmp_path: Path):
    adapter = _adapter(tmp_path)
    repo = "mlx-community/Meta-Llama-3.1-8B-Instruct-4bit"
    assert adapter.resolved_model_id(repo, tmp_path / "snap") == repo


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
