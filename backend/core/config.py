"""Application configuration.

Deploy-level secrets and defaults come from the environment / ``.env`` before
first boot. Runtime-mutable user settings live in the DB and are
not modeled here.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ODYSSEUS_", env_file=".env", extra="ignore"
    )

    version: str = "0.1.0"
    environment: str = "development"

    host: str = "127.0.0.1"
    # 8000, not 7000: macOS AirPlay Receiver squats on :7000 (wildcard, both IP
    # stacks), shadowing an IPv4-only bind when localhost resolves to ::1.
    port: int = 8000

    # Origin-agnostic: the frontend origins allowed to call the API.
    cors_origins: list[str] = ["http://localhost:5173"]

    auth_enabled: bool = True

    # All user data lives under here — gitignored, encrypted at rest.
    data_dir: Path = Path("data")
    # DB connection. None ⇒ a file under data_dir; tests pass an in-memory URL.
    db_url: str | None = None
    # Unlock passphrase for the at-rest encryption vault. When set, the vault is
    # set up (first run) or unlocked at boot without a login — the auth-disabled
    # path. With auth enabled the operator unlocks via login instead.
    unlock_passphrase: str | None = None

    # Run substrate bounds. Timeouts are seconds; None disables.
    run_max_concurrency: int = 8
    run_wall_clock_timeout_s: float | None = 1800.0
    run_inactivity_timeout_s: float | None = 120.0

    # Model resolution is the DB-backed registry's job (services/registry.py) —
    # named roles bound to ordered endpoint chains, the single source of truth,
    # populated by manual config (the /models surface) today and the automatic
    # setup / Cookbook later. There is deliberately no env model seam.

    # Agent bounds: max model requests per turn and optional per-turn
    # tool-call cap. None disables the tool cap.
    agent_request_limit: int = 25
    agent_tool_calls_limit: int | None = None

    # Execution sandbox. Agent code/shell runs isolated from the host; when no
    # runtime is available the capability is disabled (fail closed — never a host
    # fallback). `sandbox_runtime` pins docker/podman; None auto-detects.
    sandbox_enabled: bool = True
    sandbox_runtime: str | None = None
    sandbox_image: str = "python:3.12-slim"
    sandbox_memory: str = "512m"
    sandbox_cpus: str = "1.0"
    # Per-conversation live sandbox: a container lazily spun up on the first code
    # execution and kept warm so the agent can iterate (fix an error, reuse an
    # installed dependency) without rebuilding. Idle sessions are reaped to free
    # resources; the workspace (the agent's files) is preserved across reaps,
    # sealed with the vault while dormant. `idle_ttl` is how long a session may sit
    # unused before it is killed; `reap_interval` is how often the reaper sweeps.
    sandbox_session_idle_ttl_s: float = 1800.0
    sandbox_session_reap_interval_s: float = 60.0
    # Live preview: the agent runs a dev server in the sandbox and the backend
    # reverse-proxies it to the frontend. How long to wait for that server to start
    # listening before reporting the start as failed (back to the agent).
    sandbox_preview_startup_timeout_s: float = 20.0
    # What a reap preserves: the agent's own files and any output it produced.
    # These names/globs are dropped from the sealed copy — virtual environments
    # and language caches are bloat that is cheaper to rebuild than to store.
    sandbox_session_seal_excludes: tuple[str, ...] = (
        ".venv", "venv", "env", "__pycache__", "node_modules", ".git",
        ".mypy_cache", ".pytest_cache", ".ruff_cache", ".cache", "dist", "build",
        "*.pyc", "*.pyo", "*.egg-info",
    )

    # Meta-loop. The no-progress guard trips after this many identical tool
    # calls in a turn. The verifier (a post-turn judge + one bounded corrective
    # re-attempt) is off by default.
    loop_repeat_threshold: int = 3
    verify_enabled: bool = False
    # When the verifier is on, only judge turns that produced a checkable
    # artifact (made a tool call) — chitchat that called no tools is skipped.
    # Set False to judge every answer.
    verify_heuristic: bool = True

    # Web access (search + fetch). The agent reaches the web through operator-run
    # providers (SearXNG), configured in the DB-backed search registry — there is
    # no env URL seam, like the model registry. These bound the direct, SSRF-guarded
    # fetch: how long to wait, how big a page to read, and how many redirect hops to
    # follow (each re-checked by the guard). `web_search_result_limit` caps results.
    web_fetch_timeout_s: float = 15.0
    web_fetch_max_bytes: int = 2_000_000
    web_fetch_max_redirects: int = 5
    web_search_result_limit: int = 10

    # Auto-titling: name a fresh thread from its first exchange (a reasoning-off
    # utility call). On by default; the operator can rename either way. The
    # title call is best-effort and bounded by `title_timeout_s` so a slow or
    # stuck utility model can't hold the run open.
    title_enabled: bool = True
    title_timeout_s: float = 20.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
