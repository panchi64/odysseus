"""ServingService — the capability facade for local model serving.

The single home for the serve/download lifecycle the route calls (and, later, an
approval-gated agent tool). A served model is registered as a normal ``ModelEndpoint`` so
it flows through the existing resolve→role→chat path with no agent-engine changes; this
service owns everything around that — recommending an engine, downloading the model,
supervising the engine subprocess, and binding roles. The mechanical row store lives in
``store.ManagedModelStore`` and the pre-flight memory math in ``headroom``.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from pathlib import Path
from typing import Protocol

from sqlalchemy import Engine

from core.exceptions import NotFoundError, ServingError, ServingUnavailableError
from core.vault import Vault
from models.serving import ManagedModel
from services.cookbook import CookbookService
from services.credential_store import CredentialStore
from services.registry import ModelRegistry
from services.settings_store import SettingsStore

from . import headroom, recommend
from .adapters import EngineAdapter, build_adapters
from .download import DownloadManager
from .models import (
    EngineKind,
    EngineRecommendation,
    ManagedModelView,
    ServeState,
    Workload,
)
from .paths import ServingPaths, _safe, dir_size
from .store import ManagedModelStore
from .supervisor import EngineExitedDuringStartup, ProcessSupervisor

logger = logging.getLogger(__name__)

# How many times to (re)allocate a port and spawn before giving up — closes the
# bind-to-0 → spawn race where the allocated port is taken before the engine binds it.
_SPAWN_ATTEMPTS = 3
# The operator-settable preference key for the local models directory.
_MODELS_DIR_KEY = "serving.models_dir"
# The credential-store id the operator's optional HuggingFace token is stored under.
_HF_SERVICE = "huggingface"


def _remove_model_dir(artifact_path: str, repo: str) -> None:
    """Best-effort remove a deleted model's on-disk directory (blocking — run in a thread).
    Resolves the per-model dir from the recorded artifact — the dir itself for an MLX
    snapshot, the parent for a llama.cpp ``.gguf`` file — and only removes it when it's the
    expected ``_safe(repo)`` directory, never a broader tree."""
    import shutil  # noqa: PLC0415 — local to keep the import off the hot path

    p = Path(artifact_path)
    model_dir = p if p.is_dir() else p.parent
    if model_dir.name == _safe(repo):
        shutil.rmtree(model_dir, ignore_errors=True)


def _artifact_bytes(path: Path) -> int:
    """Bytes a downloaded artifact holds on disk (blocking — run in a thread): the file
    itself for a llama.cpp GGUF, or the summed snapshot for an MLX repo. ``0`` when the
    path is gone."""
    if path.is_file():
        with suppress(OSError):
            return path.stat().st_size
        return 0
    return dir_size(path)


def _ensure_writable_dir(path: Path) -> None:
    """Create ``path`` if needed and confirm we can write into it (blocking — run in a
    thread). Raises ``ServingError`` with the OS reason if it can't be used."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".odysseus-write-test"
        probe.touch()
        probe.unlink()
    except OSError as exc:
        raise ServingError(f"that models directory isn't usable: {exc}") from exc


class Reindexer(Protocol):
    """The slice of the embedding reindexer this service needs — just the trigger.
    Kept as a Protocol so serving stays decoupled from ``services.reindex``."""

    def trigger(self, owner_id: str) -> None: ...


class ServingService:
    def __init__(
        self,
        db_engine: Engine,
        vault: Vault,
        registry: ModelRegistry,
        cookbook: CookbookService,
        paths: ServingPaths,
        *,
        adapters: dict[EngineKind, EngineAdapter] | None = None,
        supervisor: ProcessSupervisor | None = None,
        reindexer: Reindexer | None = None,
        settings: SettingsStore | None = None,
        credentials: CredentialStore | None = None,
    ) -> None:
        self._store = ManagedModelStore(db_engine)
        self._vault = vault
        self._registry = registry
        self._cookbook = cookbook
        self._paths = paths
        self._downloads = DownloadManager(vault)
        self._adapters = adapters if adapters is not None else build_adapters(paths)
        self._supervisor = supervisor or ProcessSupervisor()
        self._reindexer = reindexer
        self._settings = settings
        self._credentials = credentials
        # In-flight serve jobs (download → spawn → register), one per managed model.
        self._serve_tasks: dict[str, asyncio.Task] = {}
        # Serializes serve admission so the headroom check and the state reservation it
        # guards are atomic (two concurrent serves can't both pass a stale resident set).
        self._serve_lock = asyncio.Lock()

    # --- recommendation + catalog (pure, hardware-driven) -----------------

    async def recommend_engine(self, owner_id: str) -> list[EngineRecommendation]:
        profile = await self._cookbook.detect()
        recs = recommend.recommend(profile)
        # `available` (can the host run it) is already honest from the profile; overlay
        # `installed` (is the runtime actually present) so the UI shows "ready" vs
        # "downloads the engine on first use" instead of guessing.
        for rec in recs:
            adapter = self._adapters.get(rec.engine)
            rec.installed = bool(rec.available and adapter and await adapter.is_installed())
        return recs

    async def list_repo_quants(
        self, owner_id: str, engine: EngineKind, repo: str
    ) -> list[str]:
        """The quantizations available in ``repo`` for ``engine`` — the quant picker's
        options. Best-effort and non-raising: an engine that bakes the quant into the repo
        id (MLX), an unsupported engine, or an unreachable hub yields ``[]``, so the UI
        degrades to the engine's default pick. The repo is operator-supplied free text."""
        repo = repo.strip()
        adapter = self._adapters.get(engine)
        if not repo or adapter is None:
            return []
        token = await self._hf_token(owner_id)
        return await asyncio.to_thread(adapter.list_quants, repo, token)

    # --- models directory (operator-settable) -----------------------------

    async def get_models_dir(self, owner_id: str) -> str:
        """The directory downloaded artifacts land in — the operator's configured path,
        or the built-in default under the data dir."""
        if self._settings is not None:
            configured = await self._settings.get(owner_id, _MODELS_DIR_KEY)
            if configured:
                return configured
        return str(self._paths.models_dir)

    async def set_models_dir(self, owner_id: str, path: str) -> str:
        """Point new downloads at ``path`` (created if absent). Validates it's an absolute,
        writable directory; models already on disk keep their recorded artifact paths.
        Returns the stored absolute path. Raises ``ServingError`` if it can't be used."""
        target = Path(path).expanduser()
        if not target.is_absolute():
            raise ServingError("the models directory must be an absolute path")
        if self._settings is None:
            raise ServingError("settings storage is not available")
        await asyncio.to_thread(_ensure_writable_dir, target)
        await self._settings.set(owner_id, _MODELS_DIR_KEY, str(target))
        return str(target)

    async def _model_dest(self, owner_id: str, engine: EngineKind, repo: str) -> Path:
        """Where this model's artifact should be fetched, under the configured root."""
        root = Path(await self.get_models_dir(owner_id))
        return self._paths.model_dir(engine.value, repo, root=root)

    # --- engine selection -------------------------------------------------

    def _adapter(self, engine: EngineKind) -> EngineAdapter:
        adapter = self._adapters.get(engine)
        if adapter is None:
            raise ServingUnavailableError(
                f"the {engine.value} engine is not supported on this host"
            )
        return adapter

    async def _ready_adapter(self, engine: EngineKind) -> EngineAdapter:
        """An adapter that can actually serve here — available and with its runtime in
        place (located or fetched). Used by ``serve``; ``download`` needs only format."""
        adapter = self._adapter(engine)
        if not await adapter.is_available():
            raise ServingUnavailableError(
                f"the {engine.value} engine is not available on this host"
            )
        await adapter.ensure_engine()
        return adapter

    async def _hf_token(self, owner_id: str) -> str | None:
        """The operator's optional HuggingFace token (faster downloads + gated repos), or
        ``None`` when unset, the vault is locked, or no credential store is wired."""
        if self._credentials is None:
            return None
        return await self._credentials.get_secret(owner_id, _HF_SERVICE)

    async def _headroom_inputs(
        self, owner_id: str, engine: EngineKind, repo: str, quant: str | None
    ) -> tuple[int | None, int | None]:
        """The resident-independent inputs to the pre-flight guard — the usable VRAM
        budget and the candidate's HuggingFace-reported size. Gathered **off the serve
        lock**, since the HF round-trip mustn't serialize concurrent serves; either value
        ``None`` (unknown budget, or a candidate we can't size) disables the guard."""
        usable = recommend.usable_budget(recommend.vram_budget(await self._cookbook.detect()))
        if usable is None:
            return None, None
        token = await self._hf_token(owner_id)
        need = await asyncio.to_thread(
            self._adapter(engine).download_size, repo, quant, token
        )
        return usable, need

    async def _check_headroom(
        self, owner_id: str, repo: str, usable: int | None, need_bytes: int | None
    ) -> None:
        """The in-lock half of the guard: snapshot the resident models, size them from
        their on-disk artifacts, and defer the refusal to ``headroom.check``. Cheap (local
        fs stats), so the resident snapshot and the decision stay atomic under the serve
        lock; the slow inputs were gathered by ``_headroom_inputs`` beforehand."""
        if usable is None or need_bytes is None:
            return
        resident: list[tuple[str, int]] = []
        for r in await self._store.list_rows(owner_id):
            if r.state not in headroom.RESIDENT_STATES or r.hf_repo == repo or not r.artifact_path:
                continue
            size = await asyncio.to_thread(_artifact_bytes, Path(r.artifact_path))
            resident.append((r.hf_repo, size))
        headroom.check(repo=repo, need_bytes=need_bytes, resident=resident, usable_budget=usable)

    # --- downloads --------------------------------------------------------

    async def download(
        self,
        owner_id: str,
        engine: EngineKind,
        repo: str,
        *,
        workload: Workload = Workload.chat,
        quant: str | None = None,
    ) -> ManagedModelView:
        """Download a model's artifact off the request path. Returns the managed-model
        row immediately (state ``downloading``); the UI polls ``status`` for progress."""
        row = await self._store.get_or_create(owner_id, engine, repo, workload, quant)
        # Re-downloading must not overwrite an artifact a live engine has memory-mapped:
        # tear down any in-flight serve/engine for this model and mark its endpoint
        # not-running first, then reset the row to a clean downloading state.
        await self._halt(owner_id, row.id)
        if row.endpoint_id:
            with suppress(NotFoundError):
                await self._registry.update_endpoint(
                    owner_id, row.endpoint_id, live_status="stopped"
                )
        await self._store.update(
            row.id, state=ServeState.downloading, last_error=None, port=None, pid=None
        )
        dest = await self._model_dest(owner_id, engine, repo)
        token = await self._hf_token(owner_id)
        self._start_download(row, engine, repo, quant, dest, token)
        refreshed = await self._store.get(row.id)
        return self._store.to_view(refreshed or row)

    def _start_download(
        self,
        row: ManagedModel,
        engine: EngineKind,
        repo: str,
        quant: str | None,
        dest: Path,
        token: str | None,
    ) -> None:
        """Kick off the background fetch for an existing row (shared by download + serve).
        ``dest`` is resolved by the async caller so it honors the operator's models dir;
        ``token`` is the operator's optional HuggingFace token."""
        spec = self._adapter(engine).download_spec(repo, quant, dest, token)
        self._downloads.start(row.id, dest, spec=spec, on_complete=self._make_on_complete(row.id))

    def _make_on_complete(self, managed_id: str):
        async def on_complete(artifact, error) -> None:
            if error:
                await self._store.update(managed_id, state=ServeState.error, last_error=error)
            else:
                await self._store.update(
                    managed_id,
                    state=ServeState.stopped,
                    artifact_path=str(artifact),
                    last_error=None,
                )

        return on_complete

    # --- serve / stop / delete -------------------------------------------

    async def serve(
        self,
        owner_id: str,
        engine: EngineKind,
        repo: str,
        *,
        role: str | None = None,
        workload: Workload = Workload.chat,
        quant: str | None = None,
    ) -> ManagedModelView:
        """Make a model usable: download (if needed) → launch the engine → register it
        as an endpoint → bind ``role`` (when given). **Non-blocking** — returns the row
        immediately and runs the slow work in the background, so the UI polls ``status``
        for ``downloading`` → ``starting`` → ``running`` (and surfaces ``error`` with a
        reason). Engine availability is checked up front so an unsupported engine fails
        fast."""
        adapter = self._adapter(engine)
        if not await adapter.is_available():
            raise ServingUnavailableError(
                f"the {engine.value} engine is not available on this host"
            )
        # Gather the guard's slow inputs (a HuggingFace size lookup) before taking the
        # lock, so concurrent serves don't serialize on a network round-trip.
        usable, need = await self._headroom_inputs(owner_id, engine, repo, quant)
        async with self._serve_lock:
            # Admission is serialized so two concurrent serves can't both pass the headroom
            # check against a stale resident set and then oversubscribe memory. The check
            # runs before the row is created, so a refused serve leaves no trace.
            await self._check_headroom(owner_id, repo, usable, need)
            row = await self._store.get_or_create(owner_id, engine, repo, workload, quant)
            # Cancel any prior in-flight serve for this model so it can't finish and
            # resurrect it; the new background job stops any engine still running for this
            # id before it re-spawns (supervisor.spawn clears the prior process first).
            await self._cancel_serve_task(row.id)
            await self._store.update(
                row.id, state=ServeState.starting, last_error=None, port=None, pid=None
            )
            task = asyncio.create_task(
                self._serve_bg(owner_id, row.id, engine, repo, role, quant)
            )
            self._serve_tasks[row.id] = task
            task.add_done_callback(self._make_serve_task_pruner(row.id))
        refreshed = await self._store.get(row.id)
        return self._store.to_view(refreshed or row)

    async def _serve_bg(
        self,
        owner_id: str,
        managed_id: str,
        engine: EngineKind,
        repo: str,
        role: str | None,
        quant: str | None,
    ) -> None:
        """The background half of ``serve``: ensure the runtime, download if needed,
        spawn, register, bind. All failures land on the row as ``error`` + a reason."""
        try:
            adapter = await self._ready_adapter(engine)
            row = await self._store.get(managed_id)
            if row is None:
                return
            artifact = Path(row.artifact_path) if row.artifact_path else None
            if artifact is None or not artifact.exists():
                await self._store.update(managed_id, state=ServeState.downloading, last_error=None)
                dest = await self._model_dest(owner_id, engine, repo)
                token = await self._hf_token(owner_id)
                self._start_download(row, engine, repo, quant, dest, token)
                await self._downloads.wait(managed_id)
                row = await self._store.get(managed_id)
                if row is None or row.state == ServeState.error.value:
                    return  # download failed — the row already carries the error
                artifact = Path(row.artifact_path) if row.artifact_path else None
            if artifact is None or not artifact.exists():
                raise ServingError("the model artifact is missing after download")

            await self._store.update(managed_id, state=ServeState.starting, last_error=None)
            model_id = adapter.resolved_model_id(repo, artifact)
            proc, port, base_url = await self._spawn_engine(
                managed_id, adapter, artifact, Workload(row.workload), model_id
            )
            endpoint = await self._ensure_endpoint(owner_id, row, base_url, model_id, adapter)
            # Bind the role before declaring "running", so that state means fully usable
            # (a rejected bind surfaces as last_error but leaves the engine up).
            bind_error = (
                await self._bind_role(
                    owner_id, role, endpoint.id, model_id, Workload(row.workload)
                )
                if role is not None
                else None
            )
            await self._store.update(
                managed_id,
                state=ServeState.running,
                port=port,
                pid=proc.pid,
                endpoint_id=endpoint.id,
                last_error=bind_error,
            )
        except asyncio.CancelledError:
            raise
        except ServingError as exc:
            await self._store.update(managed_id, state=ServeState.error, last_error=str(exc))
        except Exception:
            logger.exception("serving: serve failed for %s", managed_id)
            await self._store.update(
                managed_id, state=ServeState.error, last_error="serving the model failed"
            )

    async def _spawn_engine(
        self,
        managed_id: str,
        adapter: EngineAdapter,
        artifact: Path,
        workload: Workload,
        model_id: str,
    ):
        """Allocate a port, build the engine argv, and spawn it — retrying on a fresh port
        when the engine exits before it binds (the bind-to-0 → spawn race, or a port taken
        out from under us). A startup *timeout* (a slow-loading model) is not retried."""
        for attempt in range(_SPAWN_ATTEMPTS):
            port = self._supervisor.allocate_port()
            spec = adapter.serve_spec(artifact, port, workload, model_id)
            base_url = adapter.health_url(port)
            try:
                proc = await self._supervisor.spawn(
                    managed_id,
                    spec,
                    port,
                    base_url=base_url,
                    on_crash=self._make_on_crash(),
                    log_path=self._paths.log_file(managed_id),
                )
            except EngineExitedDuringStartup:
                if attempt == _SPAWN_ATTEMPTS - 1:
                    raise
                logger.warning(
                    "serving: engine for %s exited during startup; retrying on a fresh port",
                    managed_id,
                )
                continue
            return proc, port, base_url
        raise EngineExitedDuringStartup("the engine could not be started")  # unreachable

    async def _bind_role(
        self,
        owner_id: str,
        role: str,
        endpoint_id: str,
        model_id: str,
        workload: Workload,
    ) -> str | None:
        """Bind ``role`` to the served endpoint. Returns an error string when the
        registry rejects the bind (e.g. a non-tool-calling model for a tool-driving
        role, or a model that doesn't actually serve vectors) so the caller can surface
        it as ``last_error`` without tearing the running engine down — else ``None``."""
        # The embedding role pins the model explicitly (no per-conversation picker);
        # chat roles use the endpoint's default (which we set to model_id).
        pin = model_id if workload == Workload.embedding else None
        # A changed embedding binding strands existing vectors (EMB-2 segregates by
        # model), so capture the prior binding to decide whether a reindex is needed.
        prev = (
            await self._registry.get_role_binding(owner_id, role)
            if role == "embedding"
            else None
        )
        try:
            await self._registry.set_role(owner_id, role, [endpoint_id], model=pin)
        except ValueError as exc:
            return str(exc)
        # Heal semantic recall in the background when the embedding endpoint/model
        # actually changed — the same trigger the manual role-set route fires.
        if (
            role == "embedding"
            and self._reindexer is not None
            and prev != ([endpoint_id], pin)
        ):
            self._reindexer.trigger(owner_id)
        return None

    def _make_serve_task_pruner(self, managed_id: str):
        """A done-callback that drops a finished serve task from the table — but only if
        it's still the current one (a re-serve may have replaced it)."""

        def prune(task: asyncio.Task) -> None:
            if self._serve_tasks.get(managed_id) is task:
                self._serve_tasks.pop(managed_id, None)

        return prune

    async def _cancel_serve_task(self, managed_id: str) -> None:
        """Cancel and await any in-flight serve job for a model, so a stop / delete /
        re-serve can't be silently undone by the background job finishing afterward
        (which would resurrect the engine and re-enable its endpoint)."""
        task = self._serve_tasks.pop(managed_id, None)
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def _halt(self, owner_id: str, managed_id: str) -> None:
        """Tear down everything live for a model: the in-flight serve task, the download
        job, and the running engine. Leaves the row/endpoint for the caller to settle."""
        await self._cancel_serve_task(managed_id)
        await self._downloads.cancel(managed_id)
        await self._supervisor.stop(managed_id)

    async def stop(self, owner_id: str, managed_id: str) -> ManagedModelView:
        row = await self._store.get_owned(owner_id, managed_id)
        await self._halt(owner_id, managed_id)
        if row.endpoint_id:
            with suppress(NotFoundError):
                # Liveness only — the operator's own `enabled` switch is never
                # touched by the serving lifecycle.
                await self._registry.update_endpoint(
                    owner_id, row.endpoint_id, live_status="stopped"
                )
        await self._store.update(managed_id, state=ServeState.stopped, port=None, pid=None)
        refreshed = await self._store.get(managed_id)
        return self._store.to_view(refreshed or row)

    async def delete(self, owner_id: str, managed_id: str) -> None:
        row = await self._store.get_owned(owner_id, managed_id)
        await self._halt(owner_id, managed_id)
        if row.endpoint_id:
            with suppress(NotFoundError):
                await self._registry.delete_endpoint(owner_id, row.endpoint_id)
        if row.artifact_path:
            await asyncio.to_thread(_remove_model_dir, row.artifact_path, row.hf_repo)
        await self._store.delete(managed_id)

    def _make_on_crash(self):
        async def on_crash(managed_id: str, returncode: int | None) -> None:
            await self._store.update(
                managed_id,
                state=ServeState.error,
                port=None,
                pid=None,
                last_error=f"the engine exited unexpectedly (code {returncode})",
            )
            row = await self._store.get(managed_id)
            if row and row.endpoint_id:
                with suppress(NotFoundError):
                    await self._registry.update_endpoint(
                        row.owner_id, row.endpoint_id, live_status="stopped"
                    )

        return on_crash

    async def _ensure_endpoint(
        self,
        owner_id: str,
        row: ManagedModel,
        base_url: str,
        model_id: str,
        adapter: EngineAdapter,
    ):
        """Register (or refresh) the registry endpoint for a served model. Re-serving
        reuses the same endpoint so its role bindings survive a stop/start cycle."""
        if row.endpoint_id:
            try:
                await self._registry.update_endpoint(
                    owner_id,
                    row.endpoint_id,
                    base_url=base_url,
                    model=model_id,
                    live_status="running",
                    native_tools=adapter.native_tools_default,
                )
                return await self._registry.get_endpoint(owner_id, row.endpoint_id)
            except NotFoundError:
                pass  # endpoint deleted out from under us — recreate below
        # The endpoint carries the engine's generic context-window hint; the operator can
        # refine it on the endpoint if a specific repo supports more.
        context_window = adapter.context_window_hint
        return await self._registry.create_endpoint(
            owner_id,
            name=f"Local · {row.hf_repo}",
            provider="local",
            managed=True,
            live_status="running",
            base_url=base_url,
            model=model_id,
            native_tools=adapter.native_tools_default,
            vision=Workload(row.workload) == Workload.vision,
            context_window=context_window,
        )

    # --- managed-model status --------------------------------------------

    async def status(self, owner_id: str) -> list[ManagedModelView]:
        """Every managed model's current state, with live download progress and the
        bound endpoint's name overlaid. The persisted row state is the source of truth."""
        rows = await self._store.list_rows(owner_id)
        endpoints = await self._registry.list_endpoints(owner_id)
        names = {e.id: e.name for e in endpoints}
        views: list[ManagedModelView] = []
        for row in rows:
            view = self._store.to_view(row)
            if row.endpoint_id:
                view.endpoint_name = names.get(row.endpoint_id)
            progress = self._downloads.progress(row.id)
            if progress is not None:
                view.progress = progress
            views.append(view)
        return views

    async def reconcile_on_startup(self) -> None:
        """Clean up after a prior process: any model left mid-flight (running / starting
        / downloading) is clean-slated. We can't adopt an orphan engine — its process
        handle didn't survive the restart — so we best-effort terminate the recorded pid,
        mark the row ``stopped`` (clearing port/pid), and mark its endpoint not-running
        so resolve skips the dead port while the role binding (and the operator's own
        `enabled` choice) survives. Re-serving then allocates a fresh port. Fully
        best-effort: a reconcile failure must never block startup."""
        try:
            rows = await self._store.active_rows()
        except Exception:
            logger.exception("serving: reconcile could not load managed models")
            return
        for row in rows:
            if row.pid is not None:
                self._supervisor.terminate_orphan(row.pid)
            with suppress(Exception):
                await self._store.update(row.id, state=ServeState.stopped, port=None, pid=None)
            if row.endpoint_id:
                with suppress(Exception):
                    await self._registry.update_endpoint(
                        row.owner_id, row.endpoint_id, live_status="stopped"
                    )
        if rows:
            logger.info("serving: reconciled %d managed model(s) to stopped", len(rows))

    async def shutdown(self) -> None:
        """Stop every running engine and cancel in-flight serve/download work (lifespan
        teardown)."""
        for task in list(self._serve_tasks.values()):
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        await self._supervisor.stop_all()
        await self._downloads.shutdown()
