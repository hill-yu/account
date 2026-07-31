from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    app_name: str = "ADX Account Isolated Collector Control Plane"
    app_env: str = "development"
    database_url: str = f"sqlite:///{(BASE_DIR / 'control_plane.db').as_posix()}"
    sql_echo: bool = False
    collector_egress_check_url: str = "https://api.ipify.org"
    operator_remote_report_timeout_seconds: int = 15
    credential_encryption_key: str | None = None
    credential_fingerprint_key: str | None = None
    allow_stub_runtime_with_managed_credentials: bool = False

    model_config = SettingsConfigDict(
        env_prefix="ADX_COLLECTOR_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
