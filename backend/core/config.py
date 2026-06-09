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


@lru_cache
def get_settings() -> Settings:
    return Settings()
