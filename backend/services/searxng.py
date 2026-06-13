"""Managed SearXNG — web search that runs itself, so the operator never sets it up.

The agent's `search` tool needs a search backend. Rather than make the operator
stand one up and register it, the backend runs its **own** SearXNG in a container
(the same runtime the execution sandbox uses), bound to loopback, and the search
service queries it automatically. The image is refreshed to the latest tag on every
boot so the instance stays current.

Bring-up is **best-effort and non-fatal**: a missing container runtime, a failed
pull, or a server that never binds leaves :attr:`base_url` ``None`` and web search
simply degrades (no host fallback) — it never blocks app startup. The work runs in
a background task so the app boots immediately and search becomes available once the
instance is ready. The DB-backed provider registry (``models/search``) stays as an
optional override: an enabled provider there wins over this managed instance.

When ``external_base_url`` is set the operator already runs SearXNG elsewhere — we
use that URL and manage no container.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from pathlib import Path

from services.sandbox import (
    await_listening,
    detached_run_argv,
    discover_runtime,
    force_remove_container,
    published_host_port,
    run_subprocess,
)
from services.sandbox.base import SandboxError

logger = logging.getLogger(__name__)

# The one container we name, the port SearXNG listens on inside it, and the path
# its config is read from.
_CONTAINER = "odysseus-searxng"
_INTERNAL_PORT = 8080
_SETTINGS_MOUNT = "/etc/searxng/settings.yml"

# Light caps — SearXNG is a thin query proxy, not a workload.
_MEMORY = "256m"
_CPUS = "1.0"
_PIDS_LIMIT = 512

# Generated once and reused across boots so session cookies stay stable; the
# settings file itself is rewritten each boot so template changes take effect.
_SETTINGS_TEMPLATE = """\
# Managed by Odysseus — regenerated on each boot. Enables the JSON API the agent
# queries and disables the limiter (a single local operator, not a public instance).
use_default_settings: true
server:
  secret_key: "{secret_key}"
  limiter: false
  image_proxy: false
search:
  formats:
    - html
    - json
"""


class ManagedSearxng:
    """Owns the lifecycle of the backend's own SearXNG instance.

    :attr:`base_url` is ``None`` until the instance is ready (or forever, if no
    runtime is present); callers treat ``None`` as "managed search unavailable"
    and degrade. ``runtime_pref`` pins docker/podman (shared with the sandbox);
    ``None`` auto-detects.
    """

    def __init__(
        self,
        *,
        enabled: bool,
        image: str,
        data_dir: Path,
        startup_timeout_s: float,
        external_base_url: str | None = None,
        runtime_pref: str | None = None,
    ) -> None:
        self._enabled = enabled
        self._image = image
        self._dir = data_dir / "searxng"
        self._startup_timeout_s = startup_timeout_s
        self._external = external_base_url.rstrip("/") if external_base_url else None
        self._runtime_pref = runtime_pref
        self._base_url: str | None = None
        self._runtime: str | None = None
        self._task: asyncio.Task | None = None

    @property
    def base_url(self) -> str | None:
        """The instance's URL once reachable, else ``None`` (degrade web search)."""
        return self._base_url

    async def start(self) -> None:
        """Begin bring-up. Returns immediately — the container pull/launch runs in a
        background task so app startup is never blocked. A no-op when disabled."""
        if not self._enabled:
            return
        if self._external is not None:
            # The operator runs their own; nothing to manage.
            self._base_url = self._external
            logger.info("using external SearXNG at %s", self._external)
            return
        if self._task is not None:  # already bringing up — don't launch a second
            return
        self._task = asyncio.create_task(self._bring_up())

    async def stop(self) -> None:
        """Cancel an in-flight bring-up and tear down the container we launched.
        ``_bring_up`` logs its own failures, so the task only ever raises on the
        cancellation below."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._runtime is not None:
            await force_remove_container(self._runtime, _CONTAINER)

    async def _bring_up(self) -> None:
        runtime = discover_runtime(self._runtime_pref)
        if runtime is None:
            logger.info("no container runtime — managed web search unavailable")
            return
        self._runtime = runtime
        try:
            if not await self._ensure_image(runtime):
                return
            await force_remove_container(runtime, _CONTAINER)  # clear any stale one
            _timed_out, code, _out, err = await run_subprocess(
                detached_run_argv(runtime, _CONTAINER, self._flags(), self._image, []),
                timeout_s=60.0,
            )
            if code != 0:
                logger.warning(
                    "managed SearXNG failed to start: %s", err.decode("utf-8", "replace").strip()
                )
                await force_remove_container(runtime, _CONTAINER)
                return
            host_port = await published_host_port(runtime, _CONTAINER, _INTERNAL_PORT)
            await await_listening(host_port, self._startup_timeout_s)
        except SandboxError as exc:
            logger.warning("managed SearXNG did not come up: %s", exc)
            await force_remove_container(runtime, _CONTAINER)
            return
        except Exception:
            # Anything unexpected (e.g. an unwritable data dir) must not vanish into
            # the background task with no trace — log it and leave search degraded.
            logger.exception("managed SearXNG bring-up failed unexpectedly")
            await force_remove_container(runtime, _CONTAINER)
            return
        self._base_url = f"http://127.0.0.1:{host_port}"
        logger.info("managed SearXNG ready at %s", self._base_url)

    async def _ensure_image(self, runtime: str) -> bool:
        """Pull the latest image so the instance stays current. If the pull fails
        (offline) fall back to a cached image; report unavailable only if neither
        is present."""
        _timed_out, code, _out, err = await run_subprocess(
            [runtime, "pull", self._image], timeout_s=300.0
        )
        if code == 0:
            return True
        logger.warning(
            "could not pull %s (%s); trying a cached copy",
            self._image,
            err.decode("utf-8", "replace").strip(),
        )
        _t, inspect_code, _o, _e = await run_subprocess(
            [runtime, "image", "inspect", self._image], timeout_s=15.0
        )
        if inspect_code != 0:
            logger.warning("no cached %s — managed web search unavailable", self._image)
            return False
        return True

    def _flags(self) -> list[str]:
        """Isolation + the loopback-published port + the read-only config mount.
        Kept apart from the sandbox's ``hardened_flags`` (which forces a read-only
        root + ``/work`` mount that don't fit a long-lived service)."""
        settings_path = self._write_settings()
        return [
            "--network", "bridge",  # SearXNG needs egress to query upstream engines
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--memory", _MEMORY,
            "--cpus", _CPUS,
            "--pids-limit", str(_PIDS_LIMIT),
            "--publish", f"127.0.0.1:0:{_INTERNAL_PORT}",
            "--volume", f"{settings_path}:{_SETTINGS_MOUNT}:ro",
        ]

    def _write_settings(self) -> Path:
        """(Re)write the settings file from the template, reusing a persisted
        secret key so it stays stable across restarts. Returns its path."""
        self._dir.mkdir(parents=True, exist_ok=True)
        key_file = self._dir / "secret_key"
        if key_file.exists():
            secret_key = key_file.read_text().strip()
        else:
            secret_key = secrets.token_hex(32)
            key_file.write_text(secret_key)
            key_file.chmod(0o600)  # a service secret — not world-readable
        settings_path = self._dir / "settings.yml"
        settings_path.write_text(_SETTINGS_TEMPLATE.format(secret_key=secret_key))
        return settings_path
