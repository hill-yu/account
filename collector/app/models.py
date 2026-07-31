from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal


@dataclass(frozen=True)
class BootstrapSettings:
    control_plane_base_url: str
    instance_token: str
    egress_check_url: str = "https://api.ipify.org"
    request_timeout_seconds: int = 30


@dataclass(frozen=True)
class RuntimeSettings:
    control_plane_base_url: str
    instance_token: str
    proxy_protocol: str
    proxy_host: str
    proxy_port: int
    proxy_username: str | None
    proxy_password: str | None
    expected_egress_ip: str
    fetch_mode: Literal["stub", "admanager_rest", "admanager_soap"] = "stub"
    admanager_network_code: str | None = None
    google_oauth_client_id: str | None = None
    google_oauth_client_secret: str | None = None
    google_oauth_refresh_token: str | None = None
    egress_check_url: str = "https://api.ipify.org"
    request_timeout_seconds: int = 30


@dataclass(frozen=True)
class CollectorGoogleRuntimeConfig:
    fetch_mode: Literal["stub", "admanager_rest", "admanager_soap"]
    admanager_network_code: str | None = None
    google_oauth_client_id: str | None = None
    google_oauth_client_secret: str | None = None
    google_oauth_refresh_token: str | None = None


@dataclass(frozen=True)
class CollectorRuntimeConfig:
    control_plane_base_url: str
    instance_id: int
    account_id: int
    expected_egress_ip: str
    proxy_protocol: str
    proxy_host: str
    proxy_port: int
    proxy_username: str | None
    proxy_password: str | None
    egress_check_url: str
    request_timeout_seconds: int
    google: CollectorGoogleRuntimeConfig

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CollectorRuntimeConfig":
        google_payload = payload["google"]
        return cls(
            control_plane_base_url=payload["control_plane_base_url"],
            instance_id=payload["instance_id"],
            account_id=payload["account_id"],
            expected_egress_ip=payload["expected_egress_ip"],
            proxy_protocol=payload["proxy_protocol"],
            proxy_host=payload["proxy_host"],
            proxy_port=payload["proxy_port"],
            proxy_username=payload.get("proxy_username"),
            proxy_password=payload.get("proxy_password"),
            egress_check_url=payload["egress_check_url"],
            request_timeout_seconds=payload["request_timeout_seconds"],
            google=CollectorGoogleRuntimeConfig(
                fetch_mode=google_payload["fetch_mode"],
                admanager_network_code=google_payload.get("admanager_network_code"),
                google_oauth_client_id=google_payload.get("google_oauth_client_id"),
                google_oauth_client_secret=google_payload.get("google_oauth_client_secret"),
                google_oauth_refresh_token=google_payload.get("google_oauth_refresh_token"),
            ),
        )

    def to_runtime_settings(self, instance_token: str) -> RuntimeSettings:
        return RuntimeSettings(
            control_plane_base_url=self.control_plane_base_url,
            instance_token=instance_token,
            proxy_protocol=self.proxy_protocol,
            proxy_host=self.proxy_host,
            proxy_port=self.proxy_port,
            proxy_username=self.proxy_username,
            proxy_password=self.proxy_password,
            expected_egress_ip=self.expected_egress_ip,
            fetch_mode=self.google.fetch_mode,
            admanager_network_code=self.google.admanager_network_code,
            google_oauth_client_id=self.google.google_oauth_client_id,
            google_oauth_client_secret=self.google.google_oauth_client_secret,
            google_oauth_refresh_token=self.google.google_oauth_refresh_token,
            egress_check_url=self.egress_check_url,
            request_timeout_seconds=self.request_timeout_seconds,
        )


@dataclass(frozen=True)
class CollectorTask:
    id: int
    account_id: int
    collector_instance_id: int
    task_type: str
    report_date: date
    status: str
    run_reason: str = "preview"
    external_request_id: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CollectorTask":
        report_date = payload["report_date"]
        if isinstance(report_date, str):
            report_date = date.fromisoformat(report_date)
        return cls(
            id=payload["id"],
            account_id=payload["account_id"],
            collector_instance_id=payload["collector_instance_id"],
            task_type=payload["task_type"],
            run_reason=payload.get("run_reason", "preview"),
            report_date=report_date,
            status=payload["status"],
            external_request_id=payload.get("external_request_id"),
        )


@dataclass(frozen=True)
class FetchBatch:
    batch_key: str
    row_count: int
    payload_hash: str | None = None
    schema_version: str | None = None
    merge_mode: str | None = None
    touched_hours: list[int] | None = None
    expected_hour_count: int | None = None
    rows: list[dict[str, Any]] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "batch_key": self.batch_key,
            "row_count": self.row_count,
            "payload_hash": self.payload_hash,
            "schema_version": self.schema_version,
            "merge_mode": self.merge_mode,
            "touched_hours": self.touched_hours,
            "expected_hour_count": self.expected_hour_count,
            "rows": self.rows,
        }


@dataclass(frozen=True)
class RuntimeResult:
    outcome: str
    task_id: int | None = None
    reason: str | None = None
