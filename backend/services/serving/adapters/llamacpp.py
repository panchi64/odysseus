"""LlamaCppAdapter — the universal baseline engine (chat + embeddings, all platforms).

Serves GGUF models via ``llama-server``'s OpenAI-compatible API. The binary is located
(an override, a cached download under ``data/serving/engines/``, or ``llama-server`` on
PATH) and, failing that, fetched as a prebuilt release from ggml-org — no compilation.
Tool-calling rides ``--jinja`` + the model's built-in chat template; embeddings run a
separate process with ``--embeddings`` (one process per model, by design).

The prebuilt-binary fetch is best-effort: on an unsupported platform or a failed
download it raises a ``ServingError`` pointing the operator at a one-line install (e.g.
``brew install llama.cpp``). The located-binary path is the common, reliable case, and
an operator who wants CUDA/ROCm specifically builds or installs it and is found on PATH.
"""

from __future__ import annotations

import asyncio
import logging
import platform
import shutil
import stat
import tarfile
import zipfile
from ctypes.util import find_library
from pathlib import Path

import httpx

from core.exceptions import InvalidInputError, ServingError

from .. import gguf, hf
from ..download import DownloadSpec, worker_spec
from ..models import (
    EngineKind,
    LaunchOptions,
    SpeculativeMode,
    Workload,
    emit_flag,
    flag_names,
)
from ..paths import ServingPaths
from ..supervisor import ServeSpec
from .base import EngineAdapter

logger = logging.getLogger(__name__)

_BINARY = "llama-server"
_RELEASES_LATEST = "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"
# (system, machine) → that host's release build variants, best first. Assets are named
# ``llama-<tag>-bin-<variant>.<ext>``, so a variant is matched as an exact name suffix,
# never a substring: "ubuntu-x64" also *appears* in "ubuntu-openvino-2026.2.1-x64".
#
# macOS builds carry Metal, so one variant covers Apple Silicon. Linux has no CUDA or
# ROCm prebuilt (those ship for Windows only) — the Vulkan build is the sole
# GPU-accelerated option there, and the plain build runs on CPU. Vulkan is preferred
# where it can link; see ``_host_variants``.
_ASSET_VARIANTS: dict[tuple[str, str], tuple[str, ...]] = {
    ("Darwin", "arm64"): ("macos-arm64",),
    ("Darwin", "x86_64"): ("macos-x64",),
    ("Linux", "x86_64"): ("ubuntu-vulkan-x64", "ubuntu-x64"),
    ("Linux", "aarch64"): ("ubuntu-vulkan-arm64", "ubuntu-arm64"),
    ("Linux", "arm64"): ("ubuntu-vulkan-arm64", "ubuntu-arm64"),
}
# Release archive extensions, in match order: Linux/macOS ship tarballs, Windows zips.
_ARCHIVE_EXTS = (".tar.gz", ".zip")
_INSTALL_HINT = "Install llama.cpp (e.g. `brew install llama.cpp` on macOS) and retry."


class LlamaCppAdapter(EngineAdapter):
    kind = EngineKind.llama_cpp
    workloads = frozenset({Workload.chat, Workload.embedding})
    native_tools_default = True
    context_window_hint = None
    supported_options = frozenset(
        {"context_size", "kv_cache_type", "cache_reuse", "speculative", "draft_model"}
    )
    owned_flags = frozenset({"-m", "--model", "--host", "--port", "--alias", "--jinja",
                             "--embeddings"})
    # llama-server binds its port early and streams weights in behind it, so this budget
    # covers startup rather than the whole load.
    startup_timeout_s = 180.0

    def __init__(self, paths: ServingPaths, *, binary_override: str | None = None) -> None:
        self._paths = paths
        self._binary_override = binary_override
        self._binary: str | None = None

    async def is_available(self) -> bool:
        # The universal baseline: a prebuilt release exists for every target platform, so
        # the binary is fetchable without an operator step. Off that list (an exotic arch)
        # it's available only if one is already present — an honest False otherwise, since
        # ensure_engine could not obtain it.
        if _host_variants():
            return True
        return await self.is_installed()

    async def is_installed(self) -> bool:
        # Already cached, overridden, or on PATH — serving won't fetch a release binary.
        # _locate walks the engine dir + scans PATH, so run it off the event loop and
        # cache the hit: the recommendation surface calls this on every poll.
        if self._binary and Path(self._binary).exists():
            return True
        located = await asyncio.to_thread(self._locate)
        if located:
            self._binary = located
            return True
        return False

    async def ensure_engine(self) -> None:
        if self._binary and Path(self._binary).exists():
            return
        located = self._locate()
        if located:
            self._binary = located
            return
        logger.info("serving: no llama-server found; fetching a prebuilt binary")
        self._binary = await self._fetch()

    def download_spec(
        self, repo: str, quant: str | None, dest: Path, token: str | None = None
    ) -> DownloadSpec:
        # The worker resolves the GGUF file matching `quant` and fetches just that file.
        return worker_spec("file", repo, dest, quant=quant, token=token)

    def download_size(
        self, repo: str, quant: str | None, token: str | None = None
    ) -> int | None:
        # Size the single GGUF that the serve will actually fetch (the quant-matched one).
        try:
            filename = hf.gguf_filename(repo, quant, token)
        except ServingError:
            return None
        return hf.file_size(repo, filename, token)

    def list_quants(self, repo: str, token: str | None = None) -> list[str]:
        # The GGUF quants present in the repo, for the operator to pick among; an empty
        # list ⇒ the UI falls back to letting `gguf_filename` pick the default on serve.
        return hf.list_gguf_quants(repo, token)

    def serve_spec(
        self,
        artifact: Path,
        port: int,
        workload: Workload,
        model_id: str,
        options: LaunchOptions | None = None,
    ) -> ServeSpec:
        if self._binary is None:
            raise ServingError("llama.cpp is not initialized (call ensure_engine first)")
        opts = options or LaunchOptions()
        overrides = flag_names(opts.extra_args)
        argv = [self._binary]
        argv += [
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
        # Everything below is emitted only when the operator set it — and skipped when
        # their extra arguments already name the same flag, so an override reaches the
        # engine exactly once. llama-server already auto-sizes slots, GPU layers, flash
        # attention, continuous batching and prompt caching; naming those here would
        # replace its sizing with a guess.
        if opts.context_size is not None:
            argv += emit_flag(
                "-c", [str(opts.context_size)],
                aliases=frozenset({"-c", "--ctx-size"}), overrides=overrides,
            )
        if opts.kv_cache_type is not None:
            # Both halves of the cache together — quantizing K alone is rarely what an
            # operator means. -ctv wants flash attention, which defaults to auto; if the
            # pair is refused, the supervisor captures the startup log into last_error.
            argv += emit_flag(
                "-ctk", [opts.kv_cache_type.value],
                aliases=frozenset({"-ctk", "--cache-type-k"}), overrides=overrides,
            )
            argv += emit_flag(
                "-ctv", [opts.kv_cache_type.value],
                aliases=frozenset({"-ctv", "--cache-type-v"}), overrides=overrides,
            )
        if opts.cache_reuse is not None:
            argv += emit_flag(
                "--cache-reuse", [str(opts.cache_reuse)],
                aliases=frozenset({"--cache-reuse"}), overrides=overrides,
            )
        argv += self._speculative_args(artifact, opts, overrides)
        # Last, so a repeated flag the adapter also emits resolves to the operator's
        # value on engines that take the final occurrence.
        argv += opts.extra_args
        return ServeSpec(argv=argv, cwd=Path(self._binary).parent)

    def _speculative_args(
        self, artifact: Path, opts: LaunchOptions, overrides: set[str]
    ) -> list[str]:
        """Draft-token flags, when this model can actually draft.

        llama.cpp carries MTP heads **inside** the GGUF, so there is nothing to download
        and nothing for the operator to point at — the only question is whether these
        particular weights have them, which the header answers. An explicit
        ``draft_model`` is the separate-drafter case and takes precedence.
        """
        if opts.speculative is SpeculativeMode.off:
            return []
        if overrides & {"--spec-type", "-md", "--model-draft", "--spec-draft-model"}:
            return []  # the operator is driving this themselves
        if opts.draft_model:
            # A separate drafter: MTP when the *target* has the heads to verify against,
            # otherwise the ordinary draft-model path.
            kind = "draft-mtp" if self.mtp_layers(artifact) else "draft-simple"
            return ["--spec-draft-model", opts.draft_model, "--spec-type", kind]
        if self.mtp_layers(artifact):
            return ["--spec-type", "draft-mtp"]
        return []

    def mtp_layers(self, artifact: Path) -> int:
        """How many multi-token-prediction layers this GGUF carries (0 = none). Reads
        only the header, so it costs the same on a 2GB file as a 200GB one."""
        return gguf.mtp_layers(artifact)

    def describe_speculative(self, artifact: Path) -> str | None:
        layers = self.mtp_layers(artifact)
        return f"{layers} MTP layer{'s' if layers != 1 else ''} in the weights" if layers else None

    def validate_artifact(self, path: Path) -> None:
        # llama.cpp serves one GGUF file, not a directory of weights.
        if not path.exists():
            raise InvalidInputError(f"there is nothing at {path}")
        if path.is_dir():
            raise InvalidInputError(
                f"{path} is a folder — llama.cpp serves a single .gguf file, so point it "
                "at the file itself"
            )
        if path.suffix.lower() != ".gguf":
            raise InvalidInputError(
                f"{path.name} is not a .gguf file — llama.cpp only serves GGUF"
            )

    async def probe_context_window(self, port: int) -> int | None:
        """The per-slot context of the running server, read from ``/props``. This is the
        honest number: ``--ctx-size`` is the total across slots and the slot count is
        auto-sized, so the launch flag alone can't tell us what one request may use.

        The per-slot number lives under ``default_generation_settings`` (llama-server
        renders slot 0's settings there); a top-level ``n_ctx`` is only present on some
        builds, so it is the fallback rather than the primary read."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"http://127.0.0.1:{port}/props")
                resp.raise_for_status()
                props = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.info("serving: could not read /props on port %s: %s", port, exc)
            return None
        if not isinstance(props, dict):
            return None
        slot = props.get("default_generation_settings")
        n_ctx = slot.get("n_ctx") if isinstance(slot, dict) else None
        if n_ctx is None:
            n_ctx = props.get("n_ctx")
        if not isinstance(n_ctx, int) or isinstance(n_ctx, bool):
            return None
        return n_ctx if n_ctx > 0 else None

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
        variants = _host_variants()
        if not variants:
            key = (platform.system(), platform.machine())
            raise ServingError(
                f"no prebuilt llama.cpp binary for {key[0]}/{key[1]}. {_INSTALL_HINT}"
            )
        engine_dir = self._paths.engine_dir(self.kind.value)
        engine_dir.mkdir(parents=True, exist_ok=True)
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                meta = await client.get(_RELEASES_LATEST)
                meta.raise_for_status()
                asset = _pick_asset(meta.json().get("assets", []), variants)
                if asset is None:
                    raise ServingError(
                        f"no llama.cpp release asset matched any of {list(variants)}"
                    )
                # The asset name is remote input — keep only its basename so it can't
                # write outside the engine dir.
                name = Path(asset["name"]).name
                logger.info("serving: fetching llama.cpp prebuilt %s", name)
                archive_path = engine_dir / name
                async with client.stream("GET", asset["browser_download_url"]) as resp:
                    resp.raise_for_status()
                    with open(archive_path, "wb") as fh:
                        async for chunk in resp.aiter_bytes():
                            fh.write(chunk)
        except (httpx.HTTPError, KeyError, OSError) as exc:
            raise ServingError(
                f"could not download a llama.cpp binary: {exc}. {_INSTALL_HINT}"
            ) from exc
        binary = await asyncio.to_thread(_extract_server, archive_path, engine_dir)
        if binary is None:
            raise ServingError("the downloaded llama.cpp archive had no llama-server binary")
        return str(binary)


def _host_variants() -> tuple[str, ...]:
    """The release variants to try for this host, best first.

    Vulkan builds are dropped when the host has no Vulkan loader: that binary links
    against ``libvulkan``, so without it llama-server fails to start at all — strictly
    worse than the CPU build it would have displaced. With the loader present the Vulkan
    build still runs on CPU when it finds no device, so it is safe to prefer.
    """
    variants = _ASSET_VARIANTS.get((platform.system(), platform.machine()), ())
    if find_library("vulkan") is None:
        return tuple(v for v in variants if "vulkan" not in v)
    return variants


def _pick_asset(assets: list[dict], variants: tuple[str, ...]) -> dict | None:
    """The release asset for the best variant this host supports, or ``None``."""
    for variant in variants:
        suffixes = tuple(f"-bin-{variant}{ext}" for ext in _ARCHIVE_EXTS)
        for asset in assets:
            if str(asset.get("name", "")).endswith(suffixes) and asset.get(
                "browser_download_url"
            ):
                return asset
    return None


def _extract_server(archive_path: Path, dest: Path) -> Path | None:
    """Unpack a release archive and return the ``llama-server`` inside it. Linux and
    macOS assets are tarballs, Windows ones zips."""
    if archive_path.name.endswith(".zip"):
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(dest)
    else:
        with tarfile.open(archive_path) as archive:
            # `data` rejects absolute paths and links escaping dest (it is the 3.14
            # default; named here so the guarantee is explicit rather than inherited).
            archive.extractall(dest, filter="data")
    archive_path.unlink(missing_ok=True)
    for candidate in dest.rglob(_BINARY):
        if candidate.is_file():
            candidate.chmod(
                candidate.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
            )
            return candidate
    return None
