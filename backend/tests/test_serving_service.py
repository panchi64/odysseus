"""ServingService.serve/stop/delete — the registry round-trip and zero-agent-change guarantee.

Uses the FakeAdapter (a stub OpenAI server) over a real registry + DB + supervisor, so a
served model genuinely registers as an endpoint, binds a role, and resolves through the
existing ``ModelRegistry`` path unchanged.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest

from core.db import init_db, make_engine
from core.exceptions import DegradedCapabilityError, NotFoundError, ServingError
from core.vault import Vault
from services.cookbook import CookbookService
from services.registry import ModelRegistry
from services.serving import (
    EngineKind,
    ServeState,
    ServingPaths,
    ServingService,
    Workload,
)
from services.serving.adapters.fake import FakeAdapter
from services.serving.supervisor import ProcessSupervisor

OWNER = "operator"


class _FakeReindexer:
    """Records trigger() calls so a test can assert the embedding bind heals the corpus."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def trigger(self, owner_id: str) -> None:
        self.calls.append(owner_id)


class _GatedAdapter(FakeAdapter):
    """A FakeAdapter whose download blocks until the test releases it, so a stop/delete
    can deterministically race a serve that's still in flight."""

    def __init__(self) -> None:
        super().__init__()
        self.release = threading.Event()

    def download_run(self, repo: str, quant: str | None):
        inner = super().download_run(repo, quant)

        def run(dest, set_total):
            self.release.wait(timeout=10)
            return inner(dest, set_total)

        return run


async def _wait_settled(service: ServingService, managed_id: str, timeout: float = 20.0):
    """serve() is non-blocking — poll status until the model reaches a terminal state."""
    for _ in range(int(timeout / 0.05)):
        view = next((m for m in await service.status(OWNER) if m.id == managed_id), None)
        if view and view.state in (ServeState.running, ServeState.error):
            return view
        await asyncio.sleep(0.05)
    return view


async def _service(
    tmp_path: Path,
    *,
    reindexer: _FakeReindexer | None = None,
    adapter: FakeAdapter | None = None,
) -> tuple[ServingService, ModelRegistry]:
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    vault = Vault(tmp_path / "keyfile.json")
    await vault.setup("test-passphrase")
    registry = ModelRegistry(engine, vault)
    service = ServingService(
        engine,
        vault,
        registry,
        CookbookService(),
        ServingPaths(tmp_path),
        adapters={EngineKind.llama_cpp: adapter or FakeAdapter()},
        supervisor=ProcessSupervisor(startup_timeout_s=15.0, poll_interval_s=0.1),
        reindexer=reindexer,
    )
    return service, registry


async def test_serve_registers_endpoint_binds_role_and_resolves(tmp_path: Path):
    service, registry = await _service(tmp_path)
    try:
        started = await service.serve(
            OWNER, EngineKind.llama_cpp, "acme/Model-GGUF", role="main", quant="q4_k_m"
        )
        view = await _wait_settled(service, started.id)
        assert view.state == ServeState.running and view.endpoint_id and view.port

        # The served model registered as a normal 127.0.0.1 endpoint.
        endpoints = await registry.list_endpoints(OWNER)
        assert len(endpoints) == 1
        endpoint = endpoints[0]
        assert endpoint.base_url == f"http://127.0.0.1:{view.port}/v1"
        assert endpoint.model == "acme/Model-GGUF" and endpoint.native_tools is True

        # The role bound to it, and resolution works unchanged (the zero-agent-change
        # guarantee — resolve builds the Pydantic AI model without any serving knowledge).
        assert await registry.get_role(OWNER, "main") == [endpoint.id]
        model = await registry.resolve("main", owner_id=OWNER)
        assert model is not None
    finally:
        await service.shutdown()


async def test_stop_disables_endpoint_and_keeps_the_row(tmp_path: Path):
    service, registry = await _service(tmp_path)
    try:
        started = await service.serve(OWNER, EngineKind.llama_cpp, "acme/Model-GGUF", role="main")
        view = await _wait_settled(service, started.id)
        assert view.state == ServeState.running
        stopped = await service.stop(OWNER, view.id)
        assert stopped.state == ServeState.stopped and stopped.port is None

        # Endpoint kept but disabled, so resolution skips the dead port while the role
        # binding survives a stop/start cycle.
        endpoint = await registry.get_endpoint(OWNER, view.endpoint_id)
        assert endpoint.enabled is False
        assert await registry.get_role(OWNER, "main") == [view.endpoint_id]
        assert (await service.status(OWNER))[0].state == ServeState.stopped
    finally:
        await service.shutdown()


async def test_delete_removes_endpoint_and_prunes_role(tmp_path: Path):
    service, registry = await _service(tmp_path)
    try:
        started = await service.serve(OWNER, EngineKind.llama_cpp, "acme/Model-GGUF", role="main")
        view = await _wait_settled(service, started.id)
        assert view.state == ServeState.running
        await service.delete(OWNER, view.id)

        with pytest.raises(NotFoundError):
            await registry.get_endpoint(OWNER, view.endpoint_id)
        assert await registry.get_role(OWNER, "main") == []
        assert await service.status(OWNER) == []
    finally:
        await service.shutdown()


async def test_serve_embedding_binds_role_and_triggers_reindex(tmp_path: Path):
    reindexer = _FakeReindexer()
    service, registry = await _service(tmp_path, reindexer=reindexer)
    try:
        started = await service.serve(
            OWNER,
            EngineKind.llama_cpp,
            "acme/Embed-GGUF",
            role="embedding",
            workload=Workload.embedding,
        )
        view = await _wait_settled(service, started.id)
        assert view.state == ServeState.running and view.endpoint_id

        # The embedding role bound to the served endpoint, with the model pinned (the
        # embedding role has no per-conversation picker, so it resolves an explicit model).
        chain, pinned = await registry.get_role_binding(OWNER, "embedding")
        assert chain == [view.endpoint_id]
        assert pinned == "acme/Embed-GGUF"

        # A fresh embedding binding strands existing vectors, so the corpus is reindexed
        # in the background — the same heal the manual role-set route fires.
        assert reindexer.calls == [OWNER]
    finally:
        await service.shutdown()


async def test_serve_with_unknown_engine_raises(tmp_path: Path):
    service, _registry = await _service(tmp_path)
    try:
        with pytest.raises(ServingError):
            await service.serve(OWNER, EngineKind.mlx, "mlx-community/whatever")
    finally:
        await service.shutdown()


async def test_stop_during_serve_does_not_resurrect(tmp_path: Path):
    # A stop while the serve is still in flight must cancel the background job so it can't
    # finish later and resurrect the model (re-spawn the engine, re-register an endpoint).
    adapter = _GatedAdapter()
    service, registry = await _service(tmp_path, adapter=adapter)
    try:
        started = await service.serve(OWNER, EngineKind.llama_cpp, "acme/Model-GGUF", role="main")
        assert started.state in (ServeState.starting, ServeState.downloading)
        stopped = await service.stop(OWNER, started.id)
        assert stopped.state == ServeState.stopped
        # Release the (now-cancelled) download thread; the row must stay stopped.
        adapter.release.set()
        await asyncio.sleep(0.3)
        view = next(m for m in await service.status(OWNER) if m.id == started.id)
        assert view.state == ServeState.stopped and view.port is None
        # The cancelled serve never registered an endpoint.
        assert await registry.list_endpoints(OWNER) == []
    finally:
        adapter.release.set()
        await service.shutdown()


async def test_delete_during_serve_leaves_nothing(tmp_path: Path):
    adapter = _GatedAdapter()
    service, registry = await _service(tmp_path, adapter=adapter)
    try:
        started = await service.serve(OWNER, EngineKind.llama_cpp, "acme/Model-GGUF", role="main")
        await service.delete(OWNER, started.id)
        adapter.release.set()
        await asyncio.sleep(0.3)
        assert await service.status(OWNER) == []
        assert await registry.list_endpoints(OWNER) == []
    finally:
        adapter.release.set()
        await service.shutdown()


async def test_embedding_resolution_skips_a_disabled_endpoint(tmp_path: Path):
    # Stopping a served embedding model disables its endpoint but keeps the role binding;
    # embedding resolution must then degrade (skip the dead port) rather than resolve to it.
    service, registry = await _service(tmp_path)
    try:
        started = await service.serve(
            OWNER, EngineKind.llama_cpp, "acme/Embed-GGUF",
            role="embedding", workload=Workload.embedding,
        )
        view = await _wait_settled(service, started.id)
        assert view.state == ServeState.running
        assert await registry.resolve_embedding_spec(OWNER) is not None

        await service.stop(OWNER, view.id)
        with pytest.raises(DegradedCapabilityError):
            await registry.resolve_embedding_spec(OWNER)
    finally:
        await service.shutdown()


async def test_serve_threads_catalog_context_window(tmp_path: Path, monkeypatch):
    # A curated catalog repo carries a real context window; the served endpoint must carry
    # it through (rather than the adapter's generic hint or None).
    from services.cookbook.models import (
        Accelerator,
        AcceleratorKind,
        ComputeBackend,
        HardwareProfile,
        MemoryInfo,
        PlatformInfo,
    )

    gb = 1024**3

    async def big_host(self) -> HardwareProfile:
        return HardwareProfile(
            memory=MemoryInfo(total_bytes=128 * gb, available_bytes=120 * gb),
            accelerators=[
                Accelerator(
                    name="Apple M3 Max", kind=AcceleratorKind.metal,
                    vram_bytes=96 * gb, unified=True,
                )
            ],
            compute_backend=ComputeBackend.metal,
            platform=PlatformInfo(system="Darwin", release="24", arch="arm64"),
        )

    monkeypatch.setattr("services.cookbook.service.CookbookService.detect", big_host)
    service, registry = await _service(tmp_path)
    try:
        started = await service.serve(
            OWNER, EngineKind.llama_cpp, "Qwen/Qwen2.5-7B-Instruct-GGUF", quant="q4_k_m"
        )
        view = await _wait_settled(service, started.id)
        assert view.state == ServeState.running
        endpoint = await registry.get_endpoint(OWNER, view.endpoint_id)
        assert endpoint.context_window == 32768
    finally:
        await service.shutdown()
