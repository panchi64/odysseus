"""ServingService.serve/stop/delete — the registry round-trip and zero-agent-change guarantee.

Uses the FakeAdapter (a stub OpenAI server) over a real registry + DB + supervisor, so a
served model genuinely registers as an endpoint, binds a role, and resolves through the
existing ``ModelRegistry`` path unchanged.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from core.db import init_db, make_engine
from core.exceptions import (
    DegradedCapabilityError,
    InvalidInputError,
    NotFoundError,
    ServingError,
)
from core.vault import Vault
from services.cookbook import CookbookService
from services.credential_store import CredentialStore
from services.registry import ModelRegistry
from services.serving import (
    EngineKind,
    ModelSource,
    ServeStage,
    ServeState,
    ServingPaths,
    ServingService,
    Workload,
)
from services.serving.adapters.fake import FakeAdapter
from services.serving.download import DownloadSpec
from services.serving.supervisor import ProcessSupervisor
from services.settings_store import SettingsStore

OWNER = "operator"


class _FakeReindexer:
    """Records trigger() calls so a test can assert the embedding bind heals the corpus."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def trigger(self, owner_id: str) -> None:
        self.calls.append(owner_id)


class _GatedAdapter(FakeAdapter):
    """A FakeAdapter whose download child blocks until a sentinel file appears, so a
    stop/delete can deterministically race a serve that's still downloading. ``release``
    drops the sentinel; ``stop``/``delete`` instead kill the child outright."""

    def __init__(self, gate: Path) -> None:
        super().__init__()
        self._gate = gate

    def release(self) -> None:
        self._gate.touch()

    def download_spec(
        self, repo: str, quant: str | None, dest: Path, token: str | None = None
    ) -> DownloadSpec:
        code = (
            "import sys, time\n"
            "from pathlib import Path\n"
            "gate = Path(sys.argv[1]); dest = Path(sys.argv[2])\n"
            "dest.mkdir(parents=True, exist_ok=True)\n"
            "deadline = time.time() + 30\n"
            "while not gate.exists() and time.time() < deadline:\n"
            "    time.sleep(0.05)\n"
            "art = dest / 'model.gguf'; art.write_bytes(b'GGUF')\n"
            "print('ARTIFACT ' + str(art), flush=True)\n"
        )
        return DownloadSpec(argv=[sys.executable, "-c", code, str(self._gate), str(dest)])


async def _wait_settled(service: ServingService, managed_id: str, timeout: float = 20.0):
    """serve() is non-blocking — poll status until the model reaches a terminal state."""
    for _ in range(int(timeout / 0.05)):
        view = next((m for m in await service.status(OWNER) if m.id == managed_id), None)
        if view and view.state in (ServeState.running, ServeState.error):
            return view
        await asyncio.sleep(0.05)
    return view


class _TokenCapturingAdapter(FakeAdapter):
    """Records the HuggingFace token handed to ``download_spec`` so a test can assert the
    operator's stored token is threaded into the fetch."""

    def __init__(self) -> None:
        super().__init__()
        self.tokens: list[str | None] = []

    def download_spec(
        self, repo: str, quant: str | None, dest: Path, token: str | None = None
    ) -> DownloadSpec:
        self.tokens.append(token)
        return super().download_spec(repo, quant, dest, token)


async def _service(
    tmp_path: Path,
    *,
    reindexer: _FakeReindexer | None = None,
    adapter: FakeAdapter | None = None,
    hf_token: str | None = None,
) -> tuple[ServingService, ModelRegistry]:
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    vault = Vault(tmp_path / "keyfile.json")
    await vault.setup("test-passphrase")
    registry = ModelRegistry(engine, vault)
    credentials = CredentialStore(engine, vault)
    if hf_token is not None:
        await credentials.set_key(OWNER, "huggingface", hf_token)
    service = ServingService(
        engine,
        vault,
        registry,
        CookbookService(),
        ServingPaths(tmp_path),
        adapters={EngineKind.llama_cpp: adapter or FakeAdapter()},
        supervisor=ProcessSupervisor(startup_timeout_s=15.0, poll_interval_s=0.1),
        reindexer=reindexer,
        settings=SettingsStore(engine),
        credentials=credentials,
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
        # guarantee — resolution builds the Pydantic AI model without any serving
        # knowledge). Through `resolve_detailed`, which is what every caller uses.
        assert await registry.get_role(OWNER, "main") == [endpoint.id]
        resolved = await registry.resolve_detailed("main", owner_id=OWNER)
        assert resolved.model is not None
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

        # Endpoint kept but marked not-running, so resolution skips the dead port while
        # the role binding (and the operator's own `enabled` switch) survives a
        # stop/start cycle.
        endpoint = await registry.get_endpoint(OWNER, view.endpoint_id)
        assert endpoint.live_status == "stopped"
        assert endpoint.enabled is True
        assert endpoint.managed is True and endpoint.provider == "local"
        assert await registry.get_role(OWNER, "main") == [view.endpoint_id]
        assert (await service.status(OWNER))[0].state == ServeState.stopped
    finally:
        await service.shutdown()


async def test_stop_completes_and_logs_when_the_endpoint_write_fails(tmp_path, caplog):
    # Standing an endpoint down is best-effort on every teardown path: the engine is
    # already gone, and a failed write must not leave the row claiming to be running.
    # It must also not be silent — the six copies of this block disagreed, four
    # swallowing only NotFoundError and two swallowing everything without a word.
    service, registry = await _service(tmp_path)
    try:
        started = await service.serve(OWNER, EngineKind.llama_cpp, "acme/Model-GGUF", role="main")
        view = await _wait_settled(service, started.id)

        async def boom(*args, **kwargs):
            raise RuntimeError("the database went away")

        registry.update_endpoint = boom
        with caplog.at_level("ERROR"):
            stopped = await service.stop(OWNER, view.id)

        assert stopped.state == ServeState.stopped and stopped.port is None
        assert any("could not mark endpoint" in r.message for r in caplog.records)
    finally:
        await service.shutdown()


async def test_stop_is_quiet_when_the_endpoint_is_already_gone(tmp_path, caplog):
    # An endpoint deleted out from under a teardown is ordinary, not an error worth
    # logging — the row it belonged to is on its way to `stopped` either way.
    service, registry = await _service(tmp_path)
    try:
        started = await service.serve(OWNER, EngineKind.llama_cpp, "acme/Model-GGUF", role="main")
        view = await _wait_settled(service, started.id)
        await registry.delete_endpoint(OWNER, view.endpoint_id)

        with caplog.at_level("ERROR"):
            stopped = await service.stop(OWNER, view.id)

        assert stopped.state == ServeState.stopped
        assert not [r for r in caplog.records if "could not mark endpoint" in r.message]
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


async def test_delete_removes_the_artifact_directory(tmp_path: Path):
    service, _registry = await _service(tmp_path)
    try:
        started = await service.serve(
            OWNER, EngineKind.llama_cpp, "acme/Model-GGUF", quant="q4_k_m"
        )
        view = await _wait_settled(service, started.id)
        assert view.state == ServeState.running
        row = await service._store.get(view.id)
        model_dir = Path(row.artifact_path).parent
        assert model_dir.exists()

        await service.delete(OWNER, view.id)
        assert not model_dir.exists()  # the downloaded artifact is removed, not leaked
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
    adapter = _GatedAdapter(tmp_path / "release.gate")
    service, registry = await _service(tmp_path, adapter=adapter)
    try:
        started = await service.serve(OWNER, EngineKind.llama_cpp, "acme/Model-GGUF", role="main")
        assert started.state in (ServeState.starting, ServeState.downloading)
        stopped = await service.stop(OWNER, started.id)
        assert stopped.state == ServeState.stopped
        # Release the gate; the (killed) download must not resurrect the row.
        adapter.release()
        await asyncio.sleep(0.3)
        view = next(m for m in await service.status(OWNER) if m.id == started.id)
        assert view.state == ServeState.stopped and view.port is None
        # The cancelled serve never registered an endpoint.
        assert await registry.list_endpoints(OWNER) == []
    finally:
        adapter.release()
        await service.shutdown()


async def test_delete_during_serve_leaves_nothing(tmp_path: Path):
    adapter = _GatedAdapter(tmp_path / "release.gate")
    service, registry = await _service(tmp_path, adapter=adapter)
    try:
        started = await service.serve(OWNER, EngineKind.llama_cpp, "acme/Model-GGUF", role="main")
        await service.delete(OWNER, started.id)
        adapter.release()
        await asyncio.sleep(0.3)
        assert await service.status(OWNER) == []
        assert await registry.list_endpoints(OWNER) == []
    finally:
        adapter.release()
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


async def test_hf_token_is_threaded_into_downloads(tmp_path: Path):
    # The operator's stored HuggingFace token rides the fetch (faster downloads + gated
    # repos); the adapter receives it so it lands in the download child's env.
    adapter = _TokenCapturingAdapter()
    service, _registry = await _service(tmp_path, adapter=adapter, hf_token="hf_secrettoken")
    try:
        await service.download(
            OWNER, EngineKind.llama_cpp, "acme/Model-GGUF", quant="q4_k_m"
        )
        assert adapter.tokens == ["hf_secrettoken"]
    finally:
        await service.shutdown()


async def test_downloads_carry_no_token_when_unset(tmp_path: Path):
    # No stored token → the fetch runs anonymously (a token is optional, never required).
    adapter = _TokenCapturingAdapter()
    service, _registry = await _service(tmp_path, adapter=adapter)
    try:
        await service.download(
            OWNER, EngineKind.llama_cpp, "acme/Model-GGUF", quant="q4_k_m"
        )
        assert adapter.tokens == [None]
    finally:
        await service.shutdown()


async def test_serve_carries_adapter_context_window_hint(tmp_path: Path):
    # With no curated catalog, the served endpoint carries the engine adapter's generic
    # context-window hint (the operator can refine it on the endpoint afterwards).
    service, registry = await _service(tmp_path)
    try:
        started = await service.serve(
            OWNER, EngineKind.llama_cpp, "acme/Some-GGUF", quant="q4_k_m"
        )
        view = await _wait_settled(service, started.id)
        assert view.state == ServeState.running
        endpoint = await registry.get_endpoint(OWNER, view.endpoint_id)
        assert endpoint.context_window == 4096  # FakeAdapter.context_window_hint
    finally:
        await service.shutdown()


async def test_models_dir_setting_routes_downloads(tmp_path: Path):
    service, _registry = await _service(tmp_path)
    try:
        custom = tmp_path / "external" / "models"
        stored = await service.set_models_dir(OWNER, str(custom))
        assert stored == str(custom)
        assert await service.get_models_dir(OWNER) == str(custom)

        view = await service.download(
            OWNER, EngineKind.llama_cpp, "acme/Model-GGUF", quant="q4_k_m"
        )
        for _ in range(200):
            row = next((m for m in await service.status(OWNER) if m.id == view.id), None)
            if row and row.state == ServeState.stopped:
                break
            await asyncio.sleep(0.02)
        # The artifact landed under the configured directory, not the default data dir.
        assert (custom / "llama.cpp" / "acme__Model-GGUF").exists()

        with pytest.raises(InvalidInputError):
            await service.set_models_dir(OWNER, "relative/not/absolute")
    finally:
        await service.shutdown()


async def test_recommend_overlays_installed_from_adapters(tmp_path: Path):
    # The FakeAdapter (registered for llama.cpp) reports installed; an engine with no
    # registered adapter (mlx here) is not installed. `available` stays profile-derived.
    service, _registry = await _service(tmp_path)
    try:
        recs = await service.recommend_engine(OWNER)
        llama = next(r for r in recs if r.engine == EngineKind.llama_cpp)
        assert llama.installed is True
        mlx = next((r for r in recs if r.engine == EngineKind.mlx), None)
        if mlx is not None:
            assert mlx.installed is False
    finally:
        await service.shutdown()


# --- the visible starting stage ---------------------------------------------


class _SlowInstallAdapter(FakeAdapter):
    """An adapter whose runtime isn't installed yet and takes a moment to install, so a
    test can observe the stage the operator would otherwise wait through blind."""

    def __init__(self, gate: asyncio.Event) -> None:
        super().__init__()
        self._gate = gate
        self.installed = False

    async def is_installed(self) -> bool:
        return self.installed

    async def ensure_engine(self) -> None:
        await self._gate.wait()
        self.installed = True


async def _stage_of(service: ServingService, managed_id: str, want, timeout: float = 10.0):
    for _ in range(int(timeout / 0.02)):
        view = next((m for m in await service.status(OWNER) if m.id == managed_id), None)
        if view and view.stage and view.stage.stage == want:
            return view.stage
        await asyncio.sleep(0.02)
    return None


async def test_starting_reports_the_engine_install_then_the_model_load(tmp_path: Path):
    # Both steps run for minutes on a real host — the runtime install once, the weight
    # load on every serve — so `starting` alone reads as a stall.
    gate = asyncio.Event()
    adapter = _SlowInstallAdapter(gate)
    service, _ = await _service(tmp_path, adapter=adapter)
    try:
        started = await service.serve(OWNER, EngineKind.llama_cpp, "acme/Model-GGUF")
        installing = await _stage_of(service, started.id, ServeStage.installing_engine)
        assert installing is not None and installing.started_at is not None
        gate.set()

        loading = await _stage_of(service, started.id, ServeStage.loading_model)
        assert loading is not None
        # The budget rides along so the UI can say how long the wait may honestly take.
        assert loading.timeout_s == adapter.startup_timeout_s

        view = await _wait_settled(service, started.id)
        assert view.state == ServeState.running
        # A settled model is not "starting" anything.
        assert view.stage is None
    finally:
        await service.shutdown()


async def test_an_already_installed_engine_skips_the_install_stage(tmp_path: Path):
    service, _ = await _service(tmp_path)
    try:
        started = await service.serve(OWNER, EngineKind.llama_cpp, "acme/Model-GGUF")
        view = await _wait_settled(service, started.id)
        assert view.state == ServeState.running and view.stage is None
    finally:
        await service.shutdown()


async def test_a_failed_serve_leaves_no_stage_behind(tmp_path: Path):
    class _Broken(FakeAdapter):
        async def ensure_engine(self) -> None:
            raise ServingError("the runtime could not be installed")

        async def is_installed(self) -> bool:
            return False

    service, _ = await _service(tmp_path, adapter=_Broken())
    try:
        started = await service.serve(OWNER, EngineKind.llama_cpp, "acme/Model-GGUF")
        view = await _wait_settled(service, started.id)
        assert view.state == ServeState.error and view.stage is None
    finally:
        await service.shutdown()


async def test_a_serve_that_fails_after_the_endpoint_is_up_stands_it_down(tmp_path: Path):
    """A serve can fail once the endpoint already exists, and then the row is terminal —
    which startup reconcile no longer sweeps. So the failure itself has to stand the
    endpoint down, or resolution keeps treating a dead port as live and every request for
    that role fails at connect time instead of resolving to something usable."""
    service, registry = await _service(tmp_path)
    try:
        started = await service.serve(OWNER, EngineKind.llama_cpp, "acme/Model-GGUF")
        view = await _wait_settled(service, started.id)
        assert view.state == ServeState.running

        await service._fail_serve(started.id, "the engine went away")

        row = await service._store.get(started.id)
        assert row is not None
        assert row.state == ServeState.error.value and row.last_error == "the engine went away"
        assert row.port is None and row.pid is None
        endpoint = await registry.get_endpoint(OWNER, view.endpoint_id or "")
        assert endpoint.live_status == "stopped"
    finally:
        await service.shutdown()


# --- capabilities come from what actually loaded ----------------------------


class _ProbingAdapter(FakeAdapter):
    """Reports capabilities the way a real engine does — from the running server and the
    downloaded weights, not from what the operator declared."""

    def __init__(self, *, tools: bool, vision: bool, window: int) -> None:
        super().__init__()
        self._tools = tools
        self._vision = vision
        self._window = window

    async def probe_native_tools(self, port: int) -> bool:
        return self._tools

    async def probe_context_window(self, port: int) -> int | None:
        return self._window

    def detect_vision(self, artifact: Path, workload: Workload) -> bool:
        return self._vision


async def test_endpoint_capabilities_come_from_the_probes(tmp_path: Path):
    # A model can be multimodal without anyone declaring a vision workload, and its real
    # context window is rarely the engine's generic hint.
    adapter = _ProbingAdapter(tools=True, vision=True, window=131072)
    service, registry = await _service(tmp_path, adapter=adapter)
    try:
        started = await service.serve(OWNER, EngineKind.llama_cpp, "acme/Model-GGUF")
        await _wait_settled(service, started.id)
        endpoint = (await registry.list_endpoints(OWNER))[0]
        assert endpoint.vision is True
        assert endpoint.context_window == 131072
        assert endpoint.native_tools is True
    finally:
        await service.shutdown()


class _FlakyProbeAdapter(FakeAdapter):
    """Answers the context-window probe once and reports ``None`` from then on — an MLX
    ``/health`` that responds on the first serve and is unreachable (or missing the keys)
    on the next. Carries MLX's generic hint, the number that used to overwrite the real
    window on that failure."""

    context_window_hint = 32768

    def __init__(self, window: int) -> None:
        super().__init__()
        self._windows = [window]

    async def probe_context_window(self, port: int) -> int | None:
        return self._windows.pop(0) if self._windows else None


async def test_a_failed_context_window_probe_leaves_the_stored_one_alone(tmp_path: Path):
    # A probe that comes back None means "couldn't ask", not "the window shrank".
    # Falling back to the engine's generic hint there caps a measured 128K endpoint at
    # 32K — and `update_endpoint` writes it, so the lie outlives the transient failure
    # and drives context reduction against a window the model does have.
    adapter = _FlakyProbeAdapter(131072)
    service, registry = await _service(tmp_path, adapter=adapter)
    try:
        started = await service.serve(OWNER, EngineKind.llama_cpp, "acme/Model-GGUF")
        view = await _wait_settled(service, started.id)
        endpoint_id = view.endpoint_id or ""
        assert (await registry.get_endpoint(OWNER, endpoint_id)).context_window == 131072

        # Re-serve the same model; this time the probe can't reach the server.
        await service.serve(OWNER, EngineKind.llama_cpp, "acme/Model-GGUF")
        again = await _wait_settled(service, started.id)

        assert again.state == ServeState.running
        assert again.endpoint_id == endpoint_id  # the same endpoint, refreshed in place
        assert (await registry.get_endpoint(OWNER, endpoint_id)).context_window == 131072
    finally:
        await service.shutdown()


async def test_a_model_without_tool_calling_is_reported_honestly(tmp_path: Path):
    # The case worth catching: it chats fine but no request would ever produce a tool
    # call, so the chat role must refuse it rather than degrade silently.
    adapter = _ProbingAdapter(tools=False, vision=False, window=8192)
    service, registry = await _service(tmp_path, adapter=adapter)
    try:
        started = await service.serve(OWNER, EngineKind.llama_cpp, "acme/Model-GGUF")
        view = await _wait_settled(service, started.id)
        # The engine stays up and usable — only the binding is refused, with a reason.
        assert view.state == ServeState.running
        assert view.last_error and "tool" in view.last_error.lower()
        endpoint = (await registry.list_endpoints(OWNER))[0]
        assert endpoint.native_tools is False
    finally:
        await service.shutdown()


async def test_capabilities_are_refreshed_on_a_re_serve(tmp_path: Path):
    # Re-serving reuses the endpoint, so a stale flag would outlive the model that earned
    # it — the endpoint must describe what is loaded right now.
    adapter = _ProbingAdapter(tools=True, vision=True, window=131072)
    service, registry = await _service(tmp_path, adapter=adapter)
    try:
        started = await service.serve(OWNER, EngineKind.llama_cpp, "acme/Model-GGUF")
        await _wait_settled(service, started.id)
        await service.stop(OWNER, started.id)

        adapter._vision = False
        adapter._window = 4096
        again = await service.serve(OWNER, EngineKind.llama_cpp, "acme/Model-GGUF")
        await _wait_settled(service, again.id)

        endpoints = await registry.list_endpoints(OWNER)
        assert len(endpoints) == 1  # same endpoint, so the role binding survived
        assert endpoints[0].vision is False and endpoints[0].context_window == 4096
    finally:
        await service.shutdown()


# --- claiming the chat role when nothing else is usable ---------------------


async def test_a_served_model_claims_chat_when_nothing_usable_is_bound(tmp_path: Path):
    # The operator brought up their one live model; making them go and pick it as well
    # would be asking a question with only one answer.
    service, registry = await _service(tmp_path)
    try:
        started = await service.serve(OWNER, EngineKind.llama_cpp, "acme/Model-GGUF")
        view = await _wait_settled(service, started.id)
        assert await registry.get_role(OWNER, "main") == [view.endpoint_id]
    finally:
        await service.shutdown()


async def test_a_working_chat_binding_is_never_displaced(tmp_path: Path):
    # Two live models is a choice, and the choice is the operator's — their setting stands.
    service, registry = await _service(tmp_path)
    try:
        first = await _wait_settled(
            service, (await service.serve(OWNER, EngineKind.llama_cpp, "acme/First-GGUF")).id
        )
        assert await registry.get_role(OWNER, "main") == [first.endpoint_id]

        second = await _wait_settled(
            service, (await service.serve(OWNER, EngineKind.llama_cpp, "acme/Second-GGUF")).id
        )
        assert second.state == ServeState.running
        assert await registry.get_role(OWNER, "main") == [first.endpoint_id]
    finally:
        await service.shutdown()


async def test_chat_is_reclaimed_once_the_bound_model_is_no_longer_running(tmp_path: Path):
    # A binding that points at a stopped engine resolves to nothing, so the next model up
    # is again the only answer.
    service, registry = await _service(tmp_path)
    try:
        first = await _wait_settled(
            service, (await service.serve(OWNER, EngineKind.llama_cpp, "acme/First-GGUF")).id
        )
        await service.stop(OWNER, first.id)

        second = await _wait_settled(
            service, (await service.serve(OWNER, EngineKind.llama_cpp, "acme/Second-GGUF")).id
        )
        assert await registry.get_role(OWNER, "main") == [second.endpoint_id]
    finally:
        await service.shutdown()


async def test_an_embedding_model_never_claims_the_chat_role(tmp_path: Path):
    service, registry = await _service(tmp_path)
    try:
        started = await service.serve(
            OWNER, EngineKind.llama_cpp, "acme/Embed-GGUF", workload=Workload.embedding
        )
        await _wait_settled(service, started.id)
        assert await registry.get_role(OWNER, "main") == []
    finally:
        await service.shutdown()


async def test_an_explicit_role_is_still_honoured(tmp_path: Path):
    service, registry = await _service(tmp_path)
    try:
        started = await service.serve(
            OWNER, EngineKind.llama_cpp, "acme/Model-GGUF", role="utility"
        )
        view = await _wait_settled(service, started.id)
        assert await registry.get_role(OWNER, "utility") == [view.endpoint_id]
    finally:
        await service.shutdown()


# --- serving weights the operator already has -------------------------------


def _local_gguf(tmp_path: Path) -> Path:
    path = tmp_path / "elsewhere" / "Qwen3-8B.gguf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"GGUF")
    return path


async def test_an_imported_model_serves_without_downloading(tmp_path: Path):
    class _NoDownloads(FakeAdapter):
        def download_spec(self, repo, quant, dest, token=None):
            raise AssertionError("an imported model must never be downloaded")

    service, registry = await _service(tmp_path, adapter=_NoDownloads())
    try:
        artifact = _local_gguf(tmp_path)
        row = await service.import_local(OWNER, EngineKind.llama_cpp, str(artifact))
        assert row.state == ServeState.stopped and row.source is ModelSource.local

        started = await service.serve(OWNER, EngineKind.llama_cpp, row.hf_repo)
        view = await _wait_settled(service, started.id)
        assert view.state == ServeState.running
        assert (await registry.list_endpoints(OWNER))[0].base_url.endswith(f"{view.port}/v1")
    finally:
        await service.shutdown()


async def test_deleting_an_imported_model_leaves_the_operators_files_alone(tmp_path: Path):
    # The invariant that makes importing safe: the weights are theirs, at a path they
    # chose, and forgetting our row must never remove them.
    service, _ = await _service(tmp_path)
    try:
        artifact = _local_gguf(tmp_path)
        row = await service.import_local(OWNER, EngineKind.llama_cpp, str(artifact))
        await service.delete(OWNER, row.id)
        assert artifact.exists()
    finally:
        await service.shutdown()


async def test_an_imported_model_whose_files_moved_says_so(tmp_path: Path):
    # Re-downloading a repo id we invented from a local path would fetch something else
    # entirely, so this has to be a clear refusal rather than a silent substitution.
    service, _ = await _service(tmp_path)
    try:
        artifact = _local_gguf(tmp_path)
        row = await service.import_local(OWNER, EngineKind.llama_cpp, str(artifact))
        artifact.unlink()

        started = await service.serve(OWNER, EngineKind.llama_cpp, row.hf_repo)
        view = await _wait_settled(service, started.id)
        assert view.state == ServeState.error
        assert "no longer there" in view.last_error
    finally:
        await service.shutdown()


async def test_import_refuses_a_path_of_the_wrong_shape(tmp_path: Path):
    service, _ = await _service(tmp_path)
    try:
        with pytest.raises(InvalidInputError):
            await service.import_local(OWNER, EngineKind.llama_cpp, str(tmp_path / "gone.gguf"))
    finally:
        await service.shutdown()


# --- re-pointing an imported model ------------------------------------------


async def test_a_folder_name_survives_the_dots_in_it(tmp_path: Path):
    # `Path.stem` truncates at the last dot, which mangles exactly the names MLX
    # snapshots carry — and since the name is the row's natural key, two of them would
    # collide onto one row and the second would silently re-point the first.
    service, _ = await _service(tmp_path)
    try:
        imported = []
        for name in ("Qwen2.5-7B-Instruct-4bit", "Qwen2.5-14B-Instruct-4bit"):
            snap = tmp_path / name
            snap.mkdir()
            (snap / "config.json").write_text("{}")
            imported.append(
                await service.import_local(OWNER, EngineKind.llama_cpp, str(snap))
            )
        assert [m.hf_repo for m in imported] == [
            "Qwen2.5-7B-Instruct-4bit",
            "Qwen2.5-14B-Instruct-4bit",
        ]
        # Two models, two rows — not one row re-pointed twice.
        assert len({m.id for m in imported}) == 2
        assert len(await service.status(OWNER)) == 2
    finally:
        await service.shutdown()


async def test_a_file_still_drops_only_its_extension(tmp_path: Path):
    service, _ = await _service(tmp_path)
    try:
        row = await service.import_local(
            OWNER, EngineKind.llama_cpp, str(_local_gguf(tmp_path))
        )
        assert row.hf_repo == "Qwen3-8B"
    finally:
        await service.shutdown()


async def test_re_importing_over_a_running_model_stops_its_engine(tmp_path: Path):
    # The row is about to be reset to `stopped`; an engine left running behind it would
    # be unreachable to stop and would still advertise itself as live.
    service, registry = await _service(tmp_path)
    try:
        artifact = _local_gguf(tmp_path)
        row = await service.import_local(OWNER, EngineKind.llama_cpp, str(artifact))
        started = await service.serve(OWNER, EngineKind.llama_cpp, row.hf_repo)
        running = await _wait_settled(service, started.id)
        assert running.state == ServeState.running

        again = await service.import_local(OWNER, EngineKind.llama_cpp, str(artifact))
        assert again.state == ServeState.stopped
        # No stale process coordinates left pointing at the engine we just killed.
        assert again.port is None
        assert not service._supervisor.is_running(again.id)
        endpoint = await registry.get_endpoint(OWNER, running.endpoint_id)
        assert endpoint.live_status == "stopped"
    finally:
        await service.shutdown()


# --- the role pin follows the served model id -------------------------------


class _RenamingAdapter(FakeAdapter):
    """An adapter whose served model id changes between serves — what MLX does when the
    snapshot path it keys on moves."""

    model_id = "acme/Model-GGUF"

    def resolved_model_id(self, repo: str, artifact: Path) -> str:
        return self.model_id


async def test_a_role_pin_follows_the_model_id_across_a_re_serve(tmp_path: Path):
    # The pin is sent verbatim as the request's `model`. An engine that answers to a
    # different id would be asked for a model it doesn't have — and mlx-vlm resolves an
    # unrecognized name by fetching a *different* model from the HuggingFace cache.
    adapter = _RenamingAdapter()
    service, registry = await _service(tmp_path, adapter=adapter)
    try:
        started = await service.serve(
            OWNER, EngineKind.llama_cpp, "acme/Model-GGUF", role="main"
        )
        view = await _wait_settled(service, started.id)
        await registry.set_role(OWNER, "main", [view.endpoint_id], model=adapter.model_id)
        assert (await registry.get_role_binding(OWNER, "main"))[1] == "acme/Model-GGUF"

        await service.stop(OWNER, started.id)
        adapter.model_id = "/models/snapshots/acme__Model"
        again = await service.serve(OWNER, EngineKind.llama_cpp, "acme/Model-GGUF")
        await _wait_settled(service, again.id)

        chain, pinned = await registry.get_role_binding(OWNER, "main")
        assert chain == [view.endpoint_id]  # the operator's endpoint choice survives
        assert pinned == "/models/snapshots/acme__Model"
    finally:
        await service.shutdown()


async def test_a_pin_on_an_unrelated_endpoint_is_left_alone(tmp_path: Path):
    service, registry = await _service(tmp_path)
    try:
        other = await registry.create_endpoint(
            OWNER, name="Remote", base_url="https://api.example.com/v1", model="gpt-x"
        )
        await registry.set_role(OWNER, "utility", [other.id], model="gpt-x")
        started = await service.serve(OWNER, EngineKind.llama_cpp, "acme/Model-GGUF")
        await _wait_settled(service, started.id)
        assert (await registry.get_role_binding(OWNER, "utility"))[1] == "gpt-x"
    finally:
        await service.shutdown()
