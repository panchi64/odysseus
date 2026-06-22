"""HuggingFace download primitives — blocking, run in a thread by the download manager.

Isolated here so the rest of the package carries no ``huggingface_hub`` specifics and
tests have one seam to monkeypatch. Most model weights are public; an optional operator
``token`` (never required) lifts the anonymous rate limit and unlocks gated/private
repos. A real failure raises ``ServingError`` with a plain-language message; sizing is
best-effort (``None`` when the API can't be reached) and never blocks a download.
"""

from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path

from core.exceptions import ServingError


def gguf_filename(repo: str, quant: str | None, token: str | None = None) -> str:
    """Resolve which GGUF in ``repo`` to fetch — preferring one matching ``quant``.

    Picks the shortest matching name so a base single-file GGUF wins over its split
    shards (``…-00001-of-00002.gguf``), which need separate handling."""
    from huggingface_hub import HfApi

    try:
        files = HfApi(token=token).list_repo_files(repo)
    except Exception as exc:  # noqa: BLE001 — surface any hub failure as a serving error
        raise ServingError(f"could not list files in {repo}: {exc}") from exc
    ggufs = [f for f in files if f.lower().endswith(".gguf")]
    if not ggufs:
        raise ServingError(f"{repo} has no GGUF files to serve with llama.cpp")
    if quant:
        matches = [f for f in ggufs if quant.lower() in f.lower()]
        if matches:
            return min(matches, key=len)
    return min(ggufs, key=len)


def file_size(repo: str, filename: str, token: str | None = None) -> int | None:
    from huggingface_hub import HfApi

    try:
        info = HfApi(token=token).model_info(repo, files_metadata=True)
    except Exception:  # noqa: BLE001 — sizing is best-effort
        return None
    for sibling in info.siblings or []:
        if sibling.rfilename == filename:
            return sibling.size
    return None


def snapshot_size(
    repo: str, allow_patterns: list[str] | None = None, token: str | None = None
) -> int | None:
    from huggingface_hub import HfApi

    try:
        info = HfApi(token=token).model_info(repo, files_metadata=True)
    except Exception:  # noqa: BLE001 — sizing is best-effort
        return None
    total = 0
    seen = False
    for sibling in info.siblings or []:
        if sibling.size is None:
            continue
        if allow_patterns and not any(fnmatch(sibling.rfilename, p) for p in allow_patterns):
            continue
        total += sibling.size
        seen = True
    return total if seen else None


def fetch_file(repo: str, filename: str, dest: Path, token: str | None = None) -> Path:
    """Download one file from ``repo`` into ``dest`` (resumes a partial download)."""
    from huggingface_hub import hf_hub_download

    try:
        path = hf_hub_download(
            repo_id=repo, filename=filename, local_dir=str(dest), token=token
        )
    except Exception as exc:  # noqa: BLE001
        raise ServingError(f"download of {filename} from {repo} failed: {exc}") from exc
    return Path(path)


def fetch_snapshot(
    repo: str, dest: Path, allow_patterns: list[str] | None = None, token: str | None = None
) -> Path:
    """Download a repo snapshot into ``dest`` (resumes a partial download)."""
    from huggingface_hub import snapshot_download

    try:
        path = snapshot_download(
            repo_id=repo, local_dir=str(dest), allow_patterns=allow_patterns, token=token
        )
    except Exception as exc:  # noqa: BLE001
        raise ServingError(f"download of {repo} failed: {exc}") from exc
    return Path(path)
