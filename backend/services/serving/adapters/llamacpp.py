"""LlamaCppAdapter — the universal baseline engine (chat + embeddings, all platforms).

Serves GGUF models via ``llama-server``'s OpenAI-compatible API. The binary is located
(an override, a cached download under ``data/serving/engines/``, or ``llama-server`` on
PATH) and, failing that, fetched as a prebuilt release from ggml-org — no compilation.
Tool-calling rides ``--jinja`` + the model's built-in chat template; embeddings run a
separate process with ``--embeddings`` (one process per model, by design).

The prebuilt-binary fetch is best-effort: on an unsupported platform or a failed
download it raises a ``ServingError`` pointing the operator at a one-line install (e.g.
``brew install llama.cpp``). The located-binary path is the common, reliable case.
"""

from __future__ import annotations

import asyncio
import logging
import platform
import shutil
import stat
import zipfile
from pathlib import Path

import httpx

from core.exceptions import ServingError

from ..download import DownloadSpec, worker_spec
from ..models import EngineKind, Workload
from ..paths import ServingPaths
from ..supervisor import ServeSpec
from .base import EngineAdapter

logger = logging.getLogger(__name__)

_BINARY = "llama-server"
_RELEASES_LATEST = "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"
# (system, machine) → the substring identifying that host's release asset.
_ASSET_SUBSTR: dict[tuple[str, str], str] = {
    ("Darwin", "arm64"): "macos-arm64",
    ("Darwin", "x86_64"): "macos-x64",
    ("Linux", "x86_64"): "ubuntu-x64",
    ("Linux", "aarch64"): "ubuntu-arm64",
    ("Linux", "arm64"): "ubuntu-arm64",
}
_INSTALL_HINT = "Install llama.cpp (e.g. `brew install llama.cpp` on macOS) and retry."


class LlamaCppAdapter(EngineAdapter):
    kind = EngineKind.llama_cpp
    workloads = frozenset({Workload.chat, Workload.embedding})
    native_tools_default = True
    context_window_hint = None

    def __init__(self, paths: ServingPaths, *, binary_override: str | None = None) -> None:
        self._paths = paths
        self._binary_override = binary_override
        self._binary: str | None = None

    async def is_available(self) -> bool:
        # The universal baseline: the binary is locatable or fetchable on every target
        # platform. ensure_engine surfaces the rare case where it can't be obtained.
        return True

    async def is_installed(self) -> bool:
        # Already cached, overridden, or on PATH — serving won't fetch a release binary.
        return self._binary is not None or self._locate() is not None

    async def ensure_engine(self) -> None:
        if self._binary and Path(self._binary).exists():
            return
        located = self._locate()
        if located:
            self._binary = located
            return
        logger.info("serving: no llama-server found; fetching a prebuilt binary")
        self._binary = await self._fetch()

    def download_spec(self, repo: str, quant: str | None, dest: Path) -> DownloadSpec:
        # The worker resolves the GGUF file matching `quant` and fetches just that file.
        return worker_spec("file", repo, dest, quant=quant)

    def serve_spec(
        self, artifact: Path, port: int, workload: Workload, model_id: str
    ) -> ServeSpec:
        if self._binary is None:
            raise ServingError("llama.cpp is not initialized (call ensure_engine first)")
        argv = [
            self._binary,
            "-m", str(artifact),
            "--host", "127.0.0.1",
            "--port", str(port),
            "--jinja",  # enable the model's chat template → native tool-calling
            "--alias", model_id,
        ]
        if workload == Workload.embedding:
            # Embeddings run as their own process — llama-server can't serve chat and
            # embeddings at once. Pooling is left unset so llama.cpp uses the type baked
            # into the model's GGUF metadata (e.g. CLS for BGE, mean for Nomic);
            # overriding it here would silently mis-pool models that aren't mean-pooled.
            argv += ["--embeddings"]
        return ServeSpec(argv=argv, cwd=Path(self._binary).parent)

    def resolved_model_id(self, repo: str, artifact: Path) -> str:
        # The server is launched with --alias = this id, so request `model` and the
        # server's advertised model agree.
        return repo

    # --- binary resolution ------------------------------------------------

    def _locate(self) -> str | None:
        if self._binary_override and Path(self._binary_override).exists():
            return self._binary_override
        engine_dir = self._paths.engine_dir(self.kind.value)
        if engine_dir.exists():
            for candidate in engine_dir.rglob(_BINARY):
                if candidate.is_file():
                    return str(candidate)
        return shutil.which(_BINARY)

    async def _fetch(self) -> str:
        key = (platform.system(), platform.machine())
        substr = _ASSET_SUBSTR.get(key)
        if substr is None:
            raise ServingError(
                f"no prebuilt llama.cpp binary for {key[0]}/{key[1]}. {_INSTALL_HINT}"
            )
        engine_dir = self._paths.engine_dir(self.kind.value)
        engine_dir.mkdir(parents=True, exist_ok=True)
        zip_path = engine_dir / "llama.zip"
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                meta = await client.get(_RELEASES_LATEST)
                meta.raise_for_status()
                assets = meta.json().get("assets", [])
                asset = next(
                    (a for a in assets if substr in a["name"] and a["name"].endswith(".zip")),
                    None,
                )
                if asset is None:
                    raise ServingError(f"no llama.cpp release asset matched {substr!r}")
                async with client.stream("GET", asset["browser_download_url"]) as resp:
                    resp.raise_for_status()
                    with open(zip_path, "wb") as fh:
                        async for chunk in resp.aiter_bytes():
                            fh.write(chunk)
        except (httpx.HTTPError, KeyError, OSError) as exc:
            raise ServingError(
                f"could not download a llama.cpp binary: {exc}. {_INSTALL_HINT}"
            ) from exc
        binary = await asyncio.to_thread(_extract_server, zip_path, engine_dir)
        if binary is None:
            raise ServingError("the downloaded llama.cpp archive had no llama-server binary")
        return str(binary)


def _extract_server(zip_path: Path, dest: Path) -> Path | None:
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(dest)
    zip_path.unlink(missing_ok=True)
    for candidate in dest.rglob(_BINARY):
        if candidate.is_file():
            candidate.chmod(
                candidate.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
            )
            return candidate
    return None
