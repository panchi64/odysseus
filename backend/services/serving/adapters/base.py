"""EngineAdapter — the pluggable seam each inference engine implements.

An adapter knows how to make its engine available, how to download a model in its
format, how to launch the OpenAI-compatible server for it, and what model id that
server answers to. Everything around it (supervision, persistence, the registry
endpoint) is engine-agnostic and lives in the service. llama.cpp is the universal
baseline; MLX is the Apple-Silicon speed adapter (added later). Both are MIT.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..download import DownloadSpec
from ..models import EngineKind, Workload
from ..supervisor import ServeSpec


class EngineAdapter(ABC):
    kind: EngineKind
    workloads: frozenset[Workload]
    # Capability defaults seeded onto the registered endpoint. Tool-driving roles
    # require native tool-calling (AE-8.1); the curated catalog keeps chat models to
    # those with reliable tool support.
    native_tools_default: bool = True
    context_window_hint: int | None = None

    @abstractmethod
    async def is_available(self) -> bool:
        """Whether this engine can run on this host at all (platform supported + the
        runtime is present or can be obtained). ``True`` doesn't imply it's installed —
        see :meth:`is_installed`."""

    async def is_installed(self) -> bool:
        """Whether the runtime is already present locally, so serving won't pay an
        install/download step first. Distinct from :meth:`is_available` (which allows a
        fetchable-but-absent runtime); the recommendation surface uses the pair to show
        'ready' vs 'will install on first use'. Defaults to not-installed; adapters that
        can cheaply locate their runtime override this."""
        return False

    @abstractmethod
    async def ensure_engine(self) -> None:
        """Make the engine runtime present (locate or install it). Raises
        ``ServingError`` if it can't be made available."""

    @abstractmethod
    def download_spec(self, repo: str, quant: str | None, dest: Path) -> DownloadSpec:
        """How to launch the child process that fetches the model (in this engine's
        format) into ``dest`` — run and killed by the download manager."""

    @abstractmethod
    def serve_spec(
        self, artifact: Path, port: int, workload: Workload, model_id: str
    ) -> ServeSpec:
        """How to launch the OpenAI-compatible server for ``artifact`` on ``port``."""

    @abstractmethod
    def resolved_model_id(self, repo: str, artifact: Path) -> str:
        """The model id the served endpoint answers to (stored as ``endpoint.model``
        and used as the server's alias so requests and the alias agree)."""

    def health_url(self, port: int) -> str:
        """The OpenAI-compatible base URL the endpoint points at."""
        return f"http://127.0.0.1:{port}/v1"
