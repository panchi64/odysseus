"""Filesystem layout for managed serving — all under the data dir (gitignored).

``pathlib`` only, no hard-coded separators (XC-PORT-1). One place owns the layout
so a relocation lands here rather than drifting across the package.
"""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path


def _safe(repo: str) -> str:
    """Flatten a HuggingFace repo id (``org/name``) into a filesystem-safe dir."""
    return repo.replace("/", "__")


def dir_size(path: Path) -> int:
    """Total bytes of the files under ``path``, excluding HuggingFace's ``.cache`` staging
    (blobs/locks it writes under ``local_dir`` before materializing the final file). ``0``
    when the path is absent — shared by download-progress polling and artifact sizing."""
    if not path.is_dir():
        return 0
    total = 0
    for child in path.rglob("*"):
        if ".cache" in child.parts:
            continue
        with suppress(OSError):
            if child.is_file():
                total += child.stat().st_size
    return total


class ServingPaths:
    def __init__(self, data_dir: Path) -> None:
        self._root = data_dir / "serving"

    @property
    def models_dir(self) -> Path:
        return self._root / "models"

    def model_dir(self, engine: str, repo: str, *, root: Path | None = None) -> Path:
        """Where a model's downloaded artifact lives: ``<root>/<engine>/<repo>``.

        ``root`` defaults to the built-in ``serving/models`` dir; the service passes the
        operator's configured models directory when one is set (the layout under it is
        identical, so a relocation is just a different root)."""
        base = root if root is not None else self.models_dir
        return base / engine / _safe(repo)

    @property
    def engines_dir(self) -> Path:
        return self._root / "engines"

    def engine_dir(self, engine: str) -> Path:
        """Where an adapter-managed runtime lives (a llama.cpp binary, an MLX venv)."""
        return self.engines_dir / engine

    @property
    def logs_dir(self) -> Path:
        return self._root / "logs"

    def log_file(self, managed_id: str) -> Path:
        return self.logs_dir / f"{managed_id}.log"
