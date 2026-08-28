"""Multi-token prediction — detection from the weights, and the flags each engine takes.

The load-bearing rule is that **MTP is detected from the artifact, never from the
config**. Conversions routinely keep ``mtp_num_hidden_layers`` in ``config.json`` long
after dropping the tensors (every mlx-community Qwen3.5/3.8 conversion checked does
exactly this), so trusting the declaration would enable a drafter with no weights behind
it. The two engines then diverge: llama.cpp carries MTP heads *inside* the GGUF, while
the MLX pipeline splits them into a separate companion drafter repo.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from services.serving.adapters.llamacpp import LlamaCppAdapter
from services.serving.adapters.mlx import MlxAdapter
from services.serving.gguf import mtp_layers, read_metadata
from services.serving.models import LaunchOptions, SpeculativeMode, Workload
from services.serving.paths import ServingPaths

# --- a minimal GGUF writer, so the header parser is tested against real bytes ---

_UINT32, _UINT64, _STRING = 4, 10, 8


def _kv(key: str, tag: int, payload: bytes) -> bytes:
    return struct.pack("<Q", len(key)) + key.encode() + struct.pack("<I", tag) + payload


def _write_gguf(path: Path, metadata: dict[str, tuple[int, bytes]]) -> Path:
    body = b"".join(_kv(k, tag, payload) for k, (tag, payload) in metadata.items())
    path.write_bytes(
        b"GGUF"
        + struct.pack("<I", 3)          # version
        + struct.pack("<Q", 0)          # tensor count
        + struct.pack("<Q", len(metadata))
        + body
    )
    return path


def _str_val(s: str) -> tuple[int, bytes]:
    return _STRING, struct.pack("<Q", len(s)) + s.encode()


def _u32(n: int) -> tuple[int, bytes]:
    return _UINT32, struct.pack("<I", n)


def _llama(tmp_path: Path) -> LlamaCppAdapter:
    adapter = LlamaCppAdapter(ServingPaths(tmp_path))
    binary = tmp_path / "llama-server"
    binary.write_text("")
    adapter._binary = str(binary)
    return adapter


def _mlx(tmp_path: Path) -> MlxAdapter:
    adapter = MlxAdapter(ServingPaths(tmp_path))
    adapter._script = str(tmp_path / "bin" / "mlx_vlm.server")
    return adapter


# --- the GGUF header parser -------------------------------------------------


def test_metadata_round_trips_from_a_real_header(tmp_path: Path):
    path = _write_gguf(
        tmp_path / "m.gguf",
        {"general.architecture": _str_val("qwen3"), "qwen3.nextn_predict_layers": _u32(1)},
    )
    assert read_metadata(path)["general.architecture"] == "qwen3"
    assert mtp_layers(path) == 1


def test_the_layer_count_is_found_under_any_architecture(tmp_path: Path):
    # The key is namespaced by architecture, so it's matched by suffix rather than by
    # guessing which family this is.
    path = _write_gguf(
        tmp_path / "m.gguf",
        {"general.architecture": _str_val("deepseek2"), "deepseek2.nextn_predict_layers": _u32(3)},
    )
    assert mtp_layers(path) == 3


def test_a_model_without_the_key_reports_no_mtp(tmp_path: Path):
    path = _write_gguf(tmp_path / "m.gguf", {"general.architecture": _str_val("qwen3")})
    assert mtp_layers(path) == 0


@pytest.mark.parametrize("body", [b"", b"not a gguf at all", b"GGUF\x03"])
def test_an_unreadable_file_degrades_to_no_metadata(tmp_path: Path, body: bytes):
    # Never raises: a truncated download or a foreign file must read as "no MTP", not
    # take down a serve.
    path = tmp_path / "junk.gguf"
    path.write_bytes(body)
    assert read_metadata(path) == {}
    assert mtp_layers(path) == 0


def test_a_missing_file_degrades_too(tmp_path: Path):
    assert mtp_layers(tmp_path / "nope.gguf") == 0


# --- llama.cpp: MTP travels inside the GGUF ---------------------------------


def _argv(adapter, artifact, options=None) -> list[str]:
    return adapter.serve_spec(artifact, 8080, Workload.chat, "acme/m", options).argv


def test_llamacpp_enables_mtp_when_the_weights_carry_it(tmp_path: Path):
    # No drafter to download and nothing for the operator to point at — the heads are in
    # the file, so the only question is whether these weights have them.
    art = _write_gguf(
        tmp_path / "m.gguf",
        {"general.architecture": _str_val("qwen3"), "qwen3.nextn_predict_layers": _u32(1)},
    )
    argv = _argv(_llama(tmp_path), art)
    assert argv[argv.index("--spec-type") + 1] == "draft-mtp"


def test_llamacpp_stays_quiet_when_the_weights_do_not(tmp_path: Path):
    art = _write_gguf(tmp_path / "m.gguf", {"general.architecture": _str_val("qwen3")})
    assert "--spec-type" not in _argv(_llama(tmp_path), art)


def test_llamacpp_honours_an_explicit_off(tmp_path: Path):
    art = _write_gguf(
        tmp_path / "m.gguf",
        {"general.architecture": _str_val("qwen3"), "qwen3.nextn_predict_layers": _u32(1)},
    )
    argv = _argv(_llama(tmp_path), art, LaunchOptions(speculative=SpeculativeMode.off))
    assert "--spec-type" not in argv


def test_llamacpp_takes_a_separate_drafter(tmp_path: Path):
    art = _write_gguf(tmp_path / "m.gguf", {"general.architecture": _str_val("qwen3")})
    argv = _argv(_llama(tmp_path), art, LaunchOptions(draft_model="/models/draft.gguf"))
    assert argv[argv.index("--spec-draft-model") + 1] == "/models/draft.gguf"
    # No MTP heads in the target, so the plain draft-model loop rather than the MTP one.
    assert argv[argv.index("--spec-type") + 1] == "draft-simple"


def test_a_drafter_against_an_mtp_target_uses_the_mtp_loop(tmp_path: Path):
    art = _write_gguf(
        tmp_path / "m.gguf",
        {"general.architecture": _str_val("qwen3"), "qwen3.nextn_predict_layers": _u32(1)},
    )
    argv = _argv(_llama(tmp_path), art, LaunchOptions(draft_model="/models/draft.gguf"))
    assert argv[argv.index("--spec-type") + 1] == "draft-mtp"


def test_an_operator_driving_spec_type_by_hand_is_left_alone(tmp_path: Path):
    art = _write_gguf(
        tmp_path / "m.gguf",
        {"general.architecture": _str_val("qwen3"), "qwen3.nextn_predict_layers": _u32(1)},
    )
    argv = _argv(
        _llama(tmp_path),
        art,
        LaunchOptions(extra_args=["--spec-type", "ngram-simple"]),
    )
    assert argv.count("--spec-type") == 1
    assert argv[argv.index("--spec-type") + 1] == "ngram-simple"


# --- MLX: MTP is split into a companion drafter -----------------------------


def _snapshot(tmp_path: Path, tensors: list[str], *, config: dict | None = None) -> Path:
    snap = tmp_path / "snap"
    snap.mkdir(exist_ok=True)
    (snap / "config.json").write_text(json.dumps(config or {"model_type": "qwen3_5"}))
    (snap / "model.safetensors.index.json").write_text(
        json.dumps({"weight_map": {t: "model.safetensors" for t in tensors}})
    )
    return snap


def test_mlx_detects_mtp_tensors_from_the_weight_index(tmp_path: Path):
    snap = _snapshot(tmp_path, ["model.embed_tokens.weight", "mtp.layers.0.mlp.weight"])
    assert _mlx(tmp_path).mtp_layers(snap) == 1
    assert "MTP" in (_mlx(tmp_path).describe_speculative(snap) or "")


def test_mlx_ignores_a_config_that_claims_mtp_with_no_tensors(tmp_path: Path):
    # The exact shape every mlx-community Qwen3.5/3.8 conversion has: the config keeps
    # `mtp_num_hidden_layers` after the conversion dropped the tensors. Trusting it would
    # enable a drafter with nothing behind it.
    snap = _snapshot(
        tmp_path,
        ["model.embed_tokens.weight"],
        config={"model_type": "qwen3_5", "text_config": {"mtp_num_hidden_layers": 1}},
    )
    assert _mlx(tmp_path).mtp_layers(snap) == 0
    assert _mlx(tmp_path).describe_speculative(snap) is None


def test_mlx_reads_shard_headers_when_there_is_no_index(tmp_path: Path):
    snap = tmp_path / "snap"
    snap.mkdir()
    header = json.dumps({"mtp.layers.0.w": {"dtype": "F16", "shape": [1], "data_offsets": [0, 2]}})
    (snap / "model.safetensors").write_bytes(
        struct.pack("<Q", len(header)) + header.encode() + b"\x00\x00"
    )
    assert _mlx(tmp_path).mtp_layers(snap) == 1


def test_mlx_passes_the_companion_drafter_through(tmp_path: Path):
    # The real-world MLX path: `mlx-community/Qwen3.8-27B-MTP-4bit` beside the base model.
    snap = _snapshot(tmp_path, ["model.embed_tokens.weight"])
    argv = _argv(
        _mlx(tmp_path), snap, LaunchOptions(draft_model="mlx-community/Qwen3.8-27B-MTP-4bit")
    )
    assert argv[argv.index("--draft-model") + 1] == "mlx-community/Qwen3.8-27B-MTP-4bit"
    # The kind is left to mlx-vlm, which reads it off the drafter's own model_type.
    assert "--draft-kind" not in argv


def test_mlx_emits_nothing_without_a_drafter(tmp_path: Path):
    # Unlike llama.cpp there is no in-file fallback: the head lives in a separate repo,
    # so with nothing named there is nothing to enable.
    snap = _snapshot(tmp_path, ["mtp.layers.0.mlp.weight"])
    assert "--draft-model" not in _argv(_mlx(tmp_path), snap)


def test_mlx_honours_an_explicit_off(tmp_path: Path):
    snap = _snapshot(tmp_path, ["model.embed_tokens.weight"])
    argv = _argv(
        _mlx(tmp_path),
        snap,
        LaunchOptions(draft_model="mlx-community/X-MTP-4bit", speculative=SpeculativeMode.off),
    )
    assert "--draft-model" not in argv


def test_an_operator_driving_the_drafter_by_hand_is_left_alone(tmp_path: Path):
    snap = _snapshot(tmp_path, ["model.embed_tokens.weight"])
    argv = _argv(
        _mlx(tmp_path),
        snap,
        LaunchOptions(
            draft_model="mlx-community/X-MTP-4bit",
            extra_args=["--draft-model", "/somewhere/else"],
        ),
    )
    assert argv.count("--draft-model") == 1
    assert argv[argv.index("--draft-model") + 1] == "/somewhere/else"


# --- both engines accept the fields -----------------------------------------


@pytest.mark.parametrize("field", ["speculative", "draft_model"])
def test_both_engines_accept_the_speculative_fields(tmp_path: Path, field: str):
    options = LaunchOptions(**{field: "off" if field == "speculative" else "acme/draft"})
    LlamaCppAdapter(ServingPaths(tmp_path)).validate_options(options)
    MlxAdapter(ServingPaths(tmp_path)).validate_options(options)
