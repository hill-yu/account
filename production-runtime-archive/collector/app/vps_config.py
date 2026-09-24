from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = BASE_DIR.parent / "deploy" / "vps" / "env" / "adx-fetch-api.env"


class VpsApiSettings(BaseSettings):
    app_name: str = "ADX VPS Fetch API"
    bind_host: str = "127.0.0.1"
    bind_port: int = 9100
    database_url: str = f"sqlite:///{(BASE_DIR / 'vps_api.db').as_posix()}"
    sql_echo: bool = False
    request_timeout_seconds: int = 30
    egress_check_url: str = "https://api.ipify.org"
    trigger_token: str = Field(default="", validation_alias="ADX_TRIGGER_TOKEN")
    direct_collector_only: bool = Field(default=True, validation_alias="ADX_DIRECT_COLLECTOR_ONLY")

    model_config = SettingsConfigDict(
        env_prefix="ADX_VPS_",
        env_file=DEFAULT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_vps_settings() -> VpsApiSettings:
    return VpsApiSettings()
