from __future__ import annotations

import os
from collections.abc import Mapping

from app.models import BootstrapSettings, RuntimeSettings
from app.proxy import ProxyConfig


class SettingsError(ValueError):
    pass


def load_bootstrap_settings(env: Mapping[str, str] | None = None) -> BootstrapSettings:
    source = os.environ if env is None else env

    def require(name: str) -> str:
        value = source.get(name)
        if value is None or value == "":
            raise SettingsError(f"Missing required environment variable: {name}")
        return value

    def optional(name: str) -> str | None:
        value = source.get(name)
        if value is None or value == "":
            return None
        return value

    request_timeout_raw = source.get("COLLECTOR_REQUEST_TIMEOUT_SECONDS", "30")
    try:
        request_timeout_seconds = int(request_timeout_raw)
    except ValueError as exc:
        raise SettingsError("Numeric environment variables must be valid integers") from exc

    return BootstrapSettings(
        control_plane_base_url=require("CONTROL_PLANE_BASE_URL").rstrip("/"),
        instance_token=require("COLLECTOR_INSTANCE_TOKEN"),
        egress_check_url=source.get("COLLECTOR_EGRESS_CHECK_URL", "https://api.ipify.org"),
        request_timeout_seconds=request_timeout_seconds,
    )


def load_settings(env: Mapping[str, str] | None = None) -> RuntimeSettings:
    source = os.environ if env is None else env

    def require(name: str) -> str:
        value = source.get(name)
        if value is None or value == "":
            raise SettingsError(f"Missing required environment variable: {name}")
        return value

    def optional(name: str) -> str | None:
        value = source.get(name)
        if value is None or value == "":
            return None
        return value

    proxy_port_raw = require("COLLECTOR_PROXY_PORT")
    request_timeout_raw = source.get("COLLECTOR_REQUEST_TIMEOUT_SECONDS", "30")
    fetch_mode = source.get("COLLECTOR_FETCH_MODE", "stub")
    if fetch_mode not in {"stub", "admanager_rest", "admanager_soap"}:
        raise SettingsError("COLLECTOR_FETCH_MODE must be one of: stub, admanager_rest, admanager_soap")
    try:
        proxy_port = int(proxy_port_raw)
        request_timeout_seconds = int(request_timeout_raw)
    except ValueError as exc:
        raise SettingsError("Numeric environment variables must be valid integers") from exc

    admanager_network_code = optional("GOOGLE_ADMANAGER_NETWORK_CODE")
    google_oauth_client_id = optional("GOOGLE_OAUTH_CLIENT_ID")
    google_oauth_client_secret = optional("GOOGLE_OAUTH_CLIENT_SECRET")
    google_oauth_refresh_token = optional("GOOGLE_OAUTH_REFRESH_TOKEN")

    if fetch_mode in {"admanager_rest", "admanager_soap"}:
        missing_name = next(
            (
                name
                for name, value in (
                    ("GOOGLE_ADMANAGER_NETWORK_CODE", admanager_network_code),
                    ("GOOGLE_OAUTH_CLIENT_ID", google_oauth_client_id),
                    ("GOOGLE_OAUTH_CLIENT_SECRET", google_oauth_client_secret),
                    ("GOOGLE_OAUTH_REFRESH_TOKEN", google_oauth_refresh_token),
                )
                if value is None
            ),
            None,
        )
        if missing_name is not None:
            raise SettingsError(f"Missing required environment variable: {missing_name}")

    settings = RuntimeSettings(
        control_plane_base_url=require("CONTROL_PLANE_BASE_URL").rstrip("/"),
        instance_token=require("COLLECTOR_INSTANCE_TOKEN"),
        proxy_protocol=require("COLLECTOR_PROXY_PROTOCOL"),
        proxy_host=require("COLLECTOR_PROXY_HOST"),
        proxy_port=proxy_port,
        proxy_username=source.get("COLLECTOR_PROXY_USERNAME"),
        proxy_password=source.get("COLLECTOR_PROXY_PASSWORD"),
        expected_egress_ip=require("COLLECTOR_EXPECTED_EGRESS_IP"),
        fetch_mode=fetch_mode,
        admanager_network_code=admanager_network_code,
        google_oauth_client_id=google_oauth_client_id,
        google_oauth_client_secret=google_oauth_client_secret,
        google_oauth_refresh_token=google_oauth_refresh_token,
        egress_check_url=source.get("COLLECTOR_EGRESS_CHECK_URL", "https://api.ipify.org"),
        request_timeout_seconds=request_timeout_seconds,
    )

    ProxyConfig(
        protocol=settings.proxy_protocol,
        host=settings.proxy_host,
        port=settings.proxy_port,
        username=settings.proxy_username,
        password=settings.proxy_password,
        expected_egress_ip=settings.expected_egress_ip,
    )
    return settings
