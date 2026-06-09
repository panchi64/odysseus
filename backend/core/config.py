"""Application configuration.

Deploy-level secrets and defaults come from the environment / ``.env`` before
first boot (``XC-CFG-1``). Runtime-mutable user settings live in the DB and are
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
    port: int = 7000

    # Origin-agnostic: the frontend origins allowed to call the API.
    cors_origins: list[str] = ["http://localhost:5173"]

    auth_enabled: bool = True

    # All user data lives under here — gitignored, encrypted at rest.
    data_dir: Path = Path("data")

    # Run substrate bounds (XC-PERF-2). Timeouts are seconds; None disables.
    run_max_concurrency: int = 8
    run_wall_clock_timeout_s: float | None = 1800.0
    run_inactivity_timeout_s: float | None = 120.0

    # Model resolution. Minimal single-endpoint seam until the role→endpoint
    # registry lands in encrypted settings. OpenAI-compatible.
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = "not-needed"  # local servers ignore it
    llm_model: str = ""  # the `main` role; empty until configured
    utility_model: str = ""  # the `utility` role; falls back to `main`

    # Agent bounds: max model requests per turn (AE-1.5) and optional
    # per-turn tool-call cap (AE-1.6). None disables the tool cap.
    agent_request_limit: int = 25
    agent_tool_calls_limit: int | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
