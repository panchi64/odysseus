"""Read a GGUF file's key/value metadata header — enough of the format, and no more.

Why this exists: whether a model can draft its own tokens (multi-token prediction) is a
property of the weights, and for llama.cpp the answer is written in the GGUF header as
``{arch}.nextn_predict_layers``. Nothing else in the stack can answer it — the file name
can't, and the operator shouldn't have to know.

Only the header is read (a few KB at the front of a multi-gigabyte file), so this is cheap
enough to run on every serve. Deliberately hand-rolled: the alternative is pulling in the
``gguf`` package for one field, and this parser is small, total, and never raises — an
unreadable or unfamiliar file simply yields no metadata, and the caller degrades to "no
MTP" rather than refusing to serve.

Spec: https://github.com/ggml-org/ggml/blob/master/docs/gguf.md
"""

from __future__ import annotations

import logging
import struct
from pathlib import Path
from typing import BinaryIO

logger = logging.getLogger(__name__)

_MAGIC = b"GGUF"
# Value type tags, per the GGUF spec. 9 (array) and 8 (string) are handled separately.
_SCALARS: dict[int, str] = {
    0: "<B",   # uint8
    1: "<b",   # int8
    2: "<H",   # uint16
    3: "<h",   # int16
    4: "<I",   # uint32
    5: "<i",   # int32
    6: "<f",   # float32
    7: "<?",   # bool
    10: "<Q",  # uint64
    11: "<q",  # int64
    12: "<d",  # float64
}
_STRING = 8
_ARRAY = 9
# A header this large means we've lost sync with the format rather than found a real file;
# stop instead of reading a multi-gigabyte file into memory one string at a time.
_MAX_STRING = 1 << 20
_MAX_ARRAY = 1 << 24


class _Truncated(Exception):
    """The file ended mid-header."""


def _read(fh: BinaryIO, size: int) -> bytes:
    data = fh.read(size)
    if len(data) != size:
        raise _Truncated
    return data


def _scalar(fh: BinaryIO, fmt: str):
    return struct.unpack(fmt, _read(fh, struct.calcsize(fmt)))[0]


def _string(fh: BinaryIO) -> str:
    length = _scalar(fh, "<Q")
    if length > _MAX_STRING:
        raise _Truncated
    return _read(fh, length).decode("utf-8", "replace")


def _value(fh: BinaryIO, tag: int):
    fmt = _SCALARS.get(tag)
    if fmt is not None:
        return _scalar(fh, fmt)
    if tag == _STRING:
        return _string(fh)
    if tag == _ARRAY:
        element_tag = _scalar(fh, "<I")
        count = _scalar(fh, "<Q")
        if count > _MAX_ARRAY:
            raise _Truncated
        # Every element has to be consumed even though callers only ever want scalars:
        # skipping the tail would desync the stream for every key that follows.
        return [_value(fh, element_tag) for _ in range(count)]
    raise _Truncated  # an unknown tag means we're no longer where we think we are


def read_metadata(path: Path) -> dict[str, object]:
    """The GGUF header's key/value metadata, or ``{}`` when it can't be read.

    Never raises: a missing file, a non-GGUF file, a truncated download, or a future
    format revision all yield an empty mapping, so a caller can treat "no metadata" and
    "metadata says no" identically.
    """
    try:
        with open(path, "rb") as fh:
            if _read(fh, 4) != _MAGIC:
                return {}
            _version = _scalar(fh, "<I")
            _tensor_count = _scalar(fh, "<Q")
            kv_count = _scalar(fh, "<Q")
            if kv_count > _MAX_ARRAY:
                return {}
            metadata: dict[str, object] = {}
            for _ in range(kv_count):
                key = _string(fh)
                metadata[key] = _value(fh, _scalar(fh, "<I"))
            return metadata
    except (OSError, _Truncated, struct.error, ValueError) as exc:
        logger.info("serving: could not read GGUF metadata from %s: %s", path, exc)
        return {}


def mtp_layers(path: Path) -> int:
    """How many multi-token-prediction layers this GGUF carries — ``0`` when it has none.

    The count is namespaced under the model's architecture (``qwen3.nextn_predict_layers``
    and so on), so the key is found by suffix rather than by guessing the architecture.
    """
    metadata = read_metadata(path)
    for key, value in metadata.items():
        if key.endswith(".nextn_predict_layers") and isinstance(value, int):
            return max(0, int(value))
    return 0
