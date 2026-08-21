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

from core.exceptions import (
    InvalidInputError,
    NotFoundError,
    ServingError,
    ServingUnavailableError,
)
from core.vault import Vault
from models._fields import utcnow
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
    LaunchOptions,
    ManagedModelView,
    ModelSource,
    ServeStage,
    ServeStageInfo,
    ServeState,
    Workload,
)
from .paths import ServingPaths, _safe, dir_size
from .store import ManagedModelStore, launch_options, model_source
from .supervisor import EngineExitedDuringStartup, ProcessSupervisor

logger = logging.getLogger(__name__)

# How many times to (re)allocate a port and spawn before giving up — closes the
# bind-to-0 → spawn race where the allocated port is taken before the engine binds it.
_SPAWN_ATTEMPTS = 3
# How long an exit can take and still look like the port race rather than a failed model
# load. A losing bind fails on the first syscall; anything that ran longer was working.
_RACE_EXIT_S = 5.0
# The role a chat-capable model auto-binds to when the operator has nothing else usable.
_DEFAULT_CHAT_ROLE = "main"
# Distinguishes "not looked at yet" from a cached "this model has no MTP" (None).
_UNREAD = object()
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
        raise InvalidInputError(f"that models directory isn't usable: {exc}") from exc


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
        # What each starting model is doing right now. In-memory like download progress:
        # it describes a live process, so it means nothing after a restart and needs no
        # column. Overlaid onto the view in `status`.
        self._stages: dict[str, ServeStageInfo] = {}
        # artifact path → its draft-token capability note (None = none). Memoized because
        # answering means reading the artifact and `status` is polled every second.
        self._speculative: dict[str, str | None] = {}
        # Serializes serve admission so the headroom check and the state reservation it
        # guards are atomic (two concurrent serves can't both pass a stale resident set).
        self._serve_lock = asyncio.Lock()

    # --- recommendation + catalog (pure, hardware-driven) -----------------

    async def recommend_engine(self, owner_id: str) -> list[EngineRecommendation]:
        profile = await self._cookbook.detect()
        recs = recommend.recommend(profile)
        # `available` (can the host run it) is already honest from the profile; overlay
        # `installed` (is the runtime actually present) so the UI shows "ready" vs
        # "downloads the engine on first use" instead of guessing, and the adapter's own
        # tunable fields so the form offers exactly what will reach a process.
        for rec in recs:
            adapter = self._adapters.get(rec.engine)
            rec.installed = bool(rec.available and adapter and await adapter.is_installed())
            rec.supported_options = sorted(adapter.supported_options) if adapter else []
        return recs

    def validate_options(self, engine: EngineKind, options: LaunchOptions | None) -> None:
        """Reject launch overrides ``engine`` can't honour. The adapter owns the rule —
        it is the thing that knows its own flag vocabulary — so this is only the facade
        the route calls without reaching into the adapter registry itself."""
        self._adapter(engine).validate_options(options)

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
            raise InvalidInputError("the models directory must be an absolute path")
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
        self,
        owner_id: str,
        engine: EngineKind,
        repo: str,
        quant: str | None,
        local_artifact: Path | None = None,
    ) -> tuple[int | None, int | None]:
        """The resident-independent inputs to the pre-flight guard — the usable VRAM
        budget and the candidate's size. Gathered **off the serve lock**, since the HF
        round-trip mustn't serialize concurrent serves; either value ``None`` (unknown
        budget, or a candidate we can't size) disables the guard.

        A model already on disk is sized from the disk — asking HuggingFace about a repo
        id we invented from a local path would size the wrong thing, or nothing."""
        usable = recommend.usable_budget(recommend.vram_budget(await self._cookbook.detect()))
        if usable is None:
            return None, None
        if local_artifact is not None:
            return usable, await asyncio.to_thread(_artifact_bytes, local_artifact)
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
        candidates = [
            (r.hf_repo, Path(r.artifact_path))
            for r in await self._store.list_rows(owner_id)
            if r.state in headroom.RESIDENT_STATES and r.hf_repo != repo and r.artifact_path
        ]
        # One thread hop for the whole snapshot rather than one per model. `_artifact_bytes`
        # walks an MLX repo's entire directory tree, and this runs with the serve lock held:
        # awaited in a loop, a few resident models turned "cheap fs stats" into a serialized
        # queue of directory walks that every concurrent serve waited behind.
        resident = await asyncio.to_thread(
            lambda: [(repo_id, _artifact_bytes(path)) for repo_id, path in candidates]
        )
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
        await self._mark_endpoint_stopped(owner_id, row.endpoint_id)
        await self._store.update(
            row.id, state=ServeState.downloading, last_error=None, port=None, pid=None
        )
        dest = await self._model_dest(owner_id, engine, repo)
        token = await self._hf_token(owner_id)
        self._start_download(row, engine, repo, quant, dest, token)
        refreshed = await self._store.get(row.id)
        return self._store.to_view(refreshed or row)

    async def import_local(
        self,
        owner_id: str,
        engine: EngineKind,
        path: str,
        *,
        workload: Workload = Workload.chat,
        name: str | None = None,
    ) -> ManagedModelView:
        """Register weights the operator already has on disk as a managed model, ready to
        serve without downloading anything.

        The path is theirs — we read it where it is and never move, rewrite, or (on
        delete) remove it. The adapter validates the shape up front so a mistyped path is
        a clear rejection now rather than a failed spawn minutes later."""
        adapter = self._adapter(engine)
        if not await adapter.is_available():
            raise ServingUnavailableError(
                f"the {engine.value} engine is not available on this host"
            )
        artifact = Path(path.strip()).expanduser()
        if not str(artifact) or not artifact.is_absolute():
            raise InvalidInputError("point at a full path, starting from the root of the disk")
        await asyncio.to_thread(adapter.validate_artifact, artifact)
        # A folder keeps its whole name: `Path.stem` truncates at the last dot, which
        # mangles exactly the names MLX snapshots carry (`Qwen2.5-7B-…` → `Qwen2`) — and
        # since this is the row's natural key, two of them would collide onto one row.
        # Only a file's extension is worth dropping.
        display = (name or "").strip() or (
            artifact.name if artifact.is_dir() else artifact.stem or artifact.name
        )
        # Re-pointing an entry that is currently serving must tear the engine down first:
        # the row is about to be reset to `stopped`, and an engine left running behind it
        # would be unreachable to stop and still advertising itself as live.
        existing = await self._store.find(owner_id, engine, display)
        if existing is not None:
            await self._halt(owner_id, existing.id)
            await self._mark_endpoint_stopped(owner_id, existing.endpoint_id)
        row = await self._store.get_or_create(
            owner_id,
            engine,
            display,
            workload,
            None,
            source=ModelSource.local,
            artifact_path=str(artifact),
            state=ServeState.stopped,
        )
        return self._store.to_view(row)

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
        options: LaunchOptions | None = None,
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
        # lock, so concurrent serves don't serialize on a network round-trip. A model
        # imported from disk is sized locally instead.
        existing = await self._store.find(owner_id, engine, repo)
        local_artifact = (
            Path(existing.artifact_path)
            if existing is not None
            and model_source(existing) is ModelSource.local
            and existing.artifact_path
            else None
        )
        usable, need = await self._headroom_inputs(
            owner_id, engine, repo, quant, local_artifact
        )
        async with self._serve_lock:
            # Admission is serialized so two concurrent serves can't both pass the headroom
            # check against a stale resident set and then oversubscribe memory. The check
            # runs before the row is created, so a refused serve leaves no trace.
            await self._check_headroom(owner_id, repo, usable, need)
            row = await self._store.get_or_create(
                owner_id, engine, repo, workload, quant, options
            )
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
            # Installing an engine runtime is a once-per-host, multi-minute step (a uv
            # venv and its wheels, or a prebuilt binary). Say so while it happens rather
            # than leaving `starting` to read as a stall.
            if not await self._adapter(engine).is_installed():
                self._set_stage(managed_id, ServeStage.installing_engine)
            adapter = await self._ready_adapter(engine)
            row = await self._store.get(managed_id)
            if row is None:
                return
            artifact = Path(row.artifact_path) if row.artifact_path else None
            if artifact is None or not artifact.exists():
                if model_source(row) is ModelSource.local:
                    # Nothing to fall back on: these weights are the operator's, at a path
                    # they chose. Re-downloading a repo id we invented from that path
                    # would fetch something else entirely.
                    raise ServingError(
                        f"the model at {row.artifact_path} is no longer there — point at "
                        "it again, or remove this entry"
                    )
                self._clear_stage(managed_id)
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
            # Loading weights is the other long step, and on an engine that loads before
            # it binds its port it is the *whole* wait — carry the budget so the UI can
            # say how long it may honestly take.
            self._set_stage(
                managed_id, ServeStage.loading_model, timeout_s=adapter.startup_timeout_s
            )
            # The overrides live on the row, written by `serve`, so a re-serve reuses what
            # the operator last set without the caller having to thread them through.
            proc, port, base_url = await self._spawn_engine(
                managed_id,
                adapter,
                artifact,
                Workload(row.workload),
                model_id,
                launch_options(row),
            )
            endpoint = await self._ensure_endpoint(
                owner_id, row, base_url, model_id, adapter, port, artifact
            )
            # Bind the role before declaring "running", so that state means fully usable
            # (a rejected bind surfaces as last_error but leaves the engine up).
            bind_error = await self._bind_after_serve(
                owner_id, role, endpoint.id, model_id, Workload(row.workload)
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
            await self._fail_serve(managed_id, str(exc))
        except Exception:
            logger.exception("serving: serve failed for %s", managed_id)
            await self._fail_serve(managed_id, "serving the model failed")
        finally:
            # Every exit — served, refused, cancelled — leaves nothing "starting".
            self._clear_stage(managed_id)

    async def _fail_serve(self, managed_id: str, message: str) -> None:
        """Land a failed serve. The row carries the reason **and** the endpoint stops
        claiming to be running — both halves, because a serve can fail after the endpoint
        exists (the engine is up, then the bind or the final write goes wrong). Resolution
        reads ``live_status``, so an endpoint left at "running" behind a failed serve keeps
        sending its role's requests to a port with nothing listening, and the row it would
        have been reconciled from is now terminal and no longer swept at startup.

        The endpoint is read back from the store rather than from the row captured at
        entry: this attempt may be the one that created it."""
        await self._store.update(
            managed_id, state=ServeState.error, last_error=message, port=None, pid=None
        )
        row = await self._store.get(managed_id)
        if row is not None:
            await self._mark_endpoint_stopped(row.owner_id, row.endpoint_id)

    # --- the starting stage (in-memory, like download progress) -----------

    def _set_stage(
        self, managed_id: str, stage: ServeStage, *, timeout_s: float | None = None
    ) -> None:
        self._stages[managed_id] = ServeStageInfo(
            stage=stage, started_at=utcnow(), timeout_s=timeout_s
        )

    def _clear_stage(self, managed_id: str) -> None:
        self._stages.pop(managed_id, None)

    async def _bind_after_serve(
        self,
        owner_id: str,
        role: str | None,
        endpoint_id: str,
        model_id: str,
        workload: Workload,
    ) -> str | None:
        """Bind the newly-served model to a role, and decide which one when the caller
        named none.

        An explicit role is honoured as asked. Otherwise a chat-capable model claims the
        chat role **only when nothing else usable is bound** — the case where the operator
        has just brought up their one live model and would otherwise have to go and pick
        it. If a working chat model is already bound, that is their setting and it stands;
        choosing between two live models is the operator's call, not ours."""
        if role is not None:
            return await self._bind_role(owner_id, role, endpoint_id, model_id, workload)
        if workload == Workload.embedding:
            return None
        if await self._registry.role_is_usable(owner_id, _DEFAULT_CHAT_ROLE):
            return None
        return await self._bind_role(
            owner_id, _DEFAULT_CHAT_ROLE, endpoint_id, model_id, workload
        )

    async def _spawn_engine(
        self,
        managed_id: str,
        adapter: EngineAdapter,
        artifact: Path,
        workload: Workload,
        model_id: str,
        options: LaunchOptions | None = None,
    ):
        """Allocate a port, build the engine argv, and spawn it — retrying on a fresh port
        when the engine exits *quickly* before it binds (the bind-to-0 → spawn race, or a
        port taken out from under us). A startup *timeout* (a slow-loading model) is not
        retried, and neither is a slow exit: an engine that ran for a while and then died
        was loading a model, so re-running that load only pays the same failure again."""
        for attempt in range(_SPAWN_ATTEMPTS):
            port = self._supervisor.allocate_port()
            spec = adapter.serve_spec(artifact, port, workload, model_id, options)
            base_url = adapter.health_url(port)
            try:
                proc = await self._supervisor.spawn(
                    managed_id,
                    spec,
                    port,
                    base_url=base_url,
                    on_crash=self._make_on_crash(),
                    log_path=self._paths.log_file(managed_id),
                    timeout_s=adapter.startup_timeout_s,
                )
            except EngineExitedDuringStartup as exc:
                if attempt == _SPAWN_ATTEMPTS - 1 or exc.elapsed_s > _RACE_EXIT_S:
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

    async def _mark_endpoint_stopped(self, owner_id: str, endpoint_id: str | None) -> None:
        """Stand an endpoint's *liveness* down, if the model has one.

        Liveness only — the operator's own ``enabled`` switch is never touched by the
        serving lifecycle. Six paths end this way (stop, delete-and-replace, re-download,
        a crash, a failed serve, startup reconcile) and every one of them is mid-teardown
        with nothing useful to do about a write that fails, so this never raises. An
        endpoint deleted out from under us is ordinary and silent; anything else is
        logged rather than swallowed, which is what the scattered copies of this block
        disagreed about — four suppressed ``NotFoundError``, two suppressed everything.
        """
        if not endpoint_id:
            return
        try:
            await self._registry.update_endpoint(owner_id, endpoint_id, live_status="stopped")
        except NotFoundError:
            pass
        except Exception:
            logger.exception("serving: could not mark endpoint %s stopped", endpoint_id)

    async def stop(self, owner_id: str, managed_id: str) -> ManagedModelView:
        row = await self._store.get_owned(owner_id, managed_id)
        await self._halt(owner_id, managed_id)
        await self._mark_endpoint_stopped(owner_id, row.endpoint_id)
        await self._store.update(managed_id, state=ServeState.stopped, port=None, pid=None)
        refreshed = await self._store.get(managed_id)
        return self._store.to_view(refreshed or row)

    async def delete(self, owner_id: str, managed_id: str) -> None:
        row = await self._store.get_owned(owner_id, managed_id)
        await self._halt(owner_id, managed_id)
        if row.endpoint_id:
            with suppress(NotFoundError):
                await self._registry.delete_endpoint(owner_id, row.endpoint_id)
        # Only weights we fetched into the models dir are ours to remove. A model the
        # operator imported lives wherever they keep it — forgetting the row must never
        # touch the files.
        if row.artifact_path and model_source(row) is ModelSource.huggingface:
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
            if row:
                await self._mark_endpoint_stopped(row.owner_id, row.endpoint_id)

        return on_crash

    async def _ensure_endpoint(
        self,
        owner_id: str,
        row: ManagedModel,
        base_url: str,
        model_id: str,
        adapter: EngineAdapter,
        port: int,
        artifact: Path,
    ):
        """Register (or refresh) the registry endpoint for a served model. Re-serving
        reuses the same endpoint so its role bindings survive a stop/start cycle."""
        # Ask the running server what context it settled on. Refreshed on every serve, not
        # just creation: a re-serve with a new context size would otherwise leave the
        # endpoint advertising the old window.
        #
        # This deliberately overwrites a hand-edited window on a *managed* endpoint. For
        # a remote endpoint the operator's number is the only source of truth, but here
        # the server itself can be asked, and a hand-set value that disagrees with the
        # running process is simply wrong — it would drive context reduction against a
        # window the model doesn't have.
        #
        # The engine's generic hint *seeds* a window nobody knows yet; it never corrects
        # one that was measured. A ``None`` probe means "couldn't ask" — MLX answers None
        # whenever /health is unreachable or doesn't carry the keys — not "the window
        # shrank", so falling back to the hint there would let one transient probe failure
        # cap a real 128K endpoint at MLX's conservative 32768 and persist that. A failed
        # probe therefore contributes nothing on the update path: `update_endpoint` skips
        # a None and the stored window survives untouched.
        probed = await adapter.probe_context_window(port)
        # Both capabilities come from what was actually loaded, for the same reason the
        # window does: tool-calling is a property of the model's chat template and vision
        # of its config, neither of which the operator's workload choice can know. Both
        # are refreshed on every serve, so re-serving a different model on the same row
        # can't leave the endpoint advertising the previous one's abilities.
        native_tools = await adapter.probe_native_tools(port)
        vision = await asyncio.to_thread(
            adapter.detect_vision, artifact, Workload(row.workload)
        )
        if row.endpoint_id:
            try:
                # The hint still gets to seed an endpoint that carries no window at all
                # (registered while the probe was down), which is the one case where a
                # generic number beats nothing.
                current = await self._registry.get_endpoint(owner_id, row.endpoint_id)
                window = probed or (
                    adapter.context_window_hint if current.context_window is None else None
                )
                await self._registry.update_endpoint(
                    owner_id,
                    row.endpoint_id,
                    base_url=base_url,
                    model=model_id,
                    live_status="running",
                    native_tools=native_tools,
                    vision=vision,
                    context_window=window,
                )
                # A role pinned to this endpoint names a model *string*, sent verbatim on
                # every request. The id an engine answers to can change under it — MLX
                # keys a model by the path it loaded from — so a pin left naming the old
                # one would ask for a model the server doesn't have.
                await self._registry.repin_roles_for_endpoint(
                    owner_id, row.endpoint_id, model_id
                )
                return await self._registry.get_endpoint(owner_id, row.endpoint_id)
            except NotFoundError:
                pass  # endpoint deleted out from under us — recreate below
        return await self._registry.create_endpoint(
            owner_id,
            name=f"Local · {row.hf_repo}",
            provider="local",
            managed=True,
            live_status="running",
            base_url=base_url,
            model=model_id,
            native_tools=native_tools,
            vision=vision,
            # Nothing is known yet on a brand-new endpoint, so here the hint is the
            # honest floor rather than a guess overwriting a measurement.
            context_window=probed or adapter.context_window_hint,
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
            # Only meaningful while the row says it's starting — a stage left over from a
            # job that has since settled would render as a wait that isn't happening.
            if view.state == ServeState.starting:
                view.stage = self._stages.get(row.id)
            view.speculative = await self._speculative_note(row)
            views.append(view)
        return views

    async def _speculative_note(self, row: ManagedModel) -> str | None:
        """What draft-token capability this model's weights carry, cached per artifact.

        Reading it means touching the file (a GGUF header, a safetensors index), and
        ``status`` is polled once a second while anything is in flight — so the answer is
        memoized against the artifact path. It only changes when the artifact does, and a
        re-download re-points the path, which invalidates the entry by construction."""
        if not row.artifact_path:
            return None
        cached = self._speculative.get(row.artifact_path, _UNREAD)
        if cached is not _UNREAD:
            return cached  # type: ignore[return-value]
        adapter = self._adapters.get(EngineKind(row.engine))
        note = (
            await asyncio.to_thread(adapter.describe_speculative, Path(row.artifact_path))
            if adapter is not None
            else None
        )
        self._speculative[row.artifact_path] = note
        return note

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
            await self._mark_endpoint_stopped(row.owner_id, row.endpoint_id)
        if rows:
            logger.info("serving: reconciled %d managed model(s) to stopped", len(rows))
        # Then the endpoints themselves, independently of the rows. A row that reached a
        # terminal state while its endpoint still claimed to be running is invisible to
        # the loop above, and that claim is what resolution trusts — left standing, it
        # points a role at a dead port for the life of the process.
        try:
            cleared = await self._registry.stop_managed_endpoints()
        except Exception:
            logger.exception("serving: reconcile could not stand down managed endpoints")
        else:
            if cleared:
                logger.info("serving: stood down %d stale managed endpoint(s)", cleared)

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
