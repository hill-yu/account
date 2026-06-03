from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AccountCreate(BaseModel):
    name: str
    status: Literal["pending", "active", "disabled"] = "pending"
    external_account_id: str | None = None


class AccountRead(ORMModel):
    id: int
    name: str
    status: str
    external_account_id: str | None
    created_at: datetime
    updated_at: datetime


class AccountList(BaseModel):
    items: list[AccountRead]


class OAuthAppCreate(BaseModel):
    account_id: int
    client_id: str
    client_secret: str
    redirect_uri: str
    scopes: str
    app_status: Literal["pending", "active", "disabled"] = "pending"
    verification_status: Literal["pending", "verified", "rejected"] = "pending"


class OAuthAppRead(ORMModel):
    id: int
    account_id: int
    client_id: str
    redirect_uri: str
    scopes: str
    app_status: str
    verification_status: str
    authorization_status: str
    authorization_requested_at: datetime | None
    authorization_completed_at: datetime | None
    access_token_expires_at: datetime | None
    refresh_token_updated_at: datetime | None
    granted_scopes: str | None
    refresh_token_present: bool
    created_at: datetime
    updated_at: datetime


class OAuthAppList(BaseModel):
    items: list[OAuthAppRead]


class AuthorizationUrlResponse(BaseModel):
    authorization_url: str
    state: str
    state_expires_at: datetime


class OAuthCallbackResponse(BaseModel):
    oauth_app_id: int
    account_id: int
    authorization_status: str
    refresh_token_present: bool


class CollectorGoogleRuntimeCredentials(BaseModel):
    fetch_mode: Literal["stub", "admanager_rest", "admanager_soap"]
    admanager_network_code: str | None = None
    google_oauth_client_id: str | None = None
    google_oauth_client_secret: str | None = None
    google_oauth_refresh_token: str | None = None


class InstanceCreate(BaseModel):
    account_id: int
    name: str
    instance_token: str | None = None
    status: Literal["provisioning", "ready", "blocked", "offline"] = "provisioning"
    expected_egress_ip: str | None = None


class InstanceRead(ORMModel):
    id: int
    account_id: int
    name: str
    status: str
    expected_egress_ip: str | None
    last_heartbeat_at: datetime | None
    created_at: datetime
    updated_at: datetime


class InstanceProvisionResponse(InstanceRead):
    instance_token: str


class InstanceList(BaseModel):
    items: list[InstanceRead]


class ProxyBindingCreate(BaseModel):
    account_id: int
    collector_instance_id: int
    provider_name: str
    protocol: Literal["http", "https", "socks5"]
    host: str
    port: int
    username: str | None = None
    password: str | None = None
    expected_egress_ip: str
    status: Literal["active", "disabled", "error"] = "active"


class ProxyBindingRead(ORMModel):
    id: int
    account_id: int
    collector_instance_id: int
    provider_name: str
    protocol: str
    host: str
    port: int
    username: str | None
    password: str | None
    expected_egress_ip: str
    status: str
    created_at: datetime
    updated_at: datetime


class ProxyBindingList(BaseModel):
    items: list[ProxyBindingRead]


class SyncTaskCreate(BaseModel):
    account_id: int
    collector_instance_id: int
    task_type: str = "report_fetch"
    report_date: date
    status: Literal["pending", "in_progress", "succeeded", "failed", "cancelled", "blocked"] = "pending"
    external_request_id: str | None = None


class SyncTaskRead(ORMModel):
    id: int
    account_id: int
    collector_instance_id: int
    task_type: str
    report_date: date
    status: str
    external_request_id: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SyncTaskList(BaseModel):
    items: list[SyncTaskRead]


class AccountDailyReportRead(ORMModel):
    id: int
    account_id: int
    report_date: date
    responses_served: int
    impressions: int
    clicks: int
    revenue: float
    ecpm: float
    created_at: datetime
    updated_at: datetime


class AccountDailyReportList(BaseModel):
    items: list[AccountDailyReportRead]


class SiteDailyReportRead(ORMModel):
    id: int
    account_id: int
    report_date: date
    url_id: str
    url: str
    responses_served: int
    impressions: int
    clicks: int
    revenue: float
    ecpm: float
    created_at: datetime
    updated_at: datetime


class SiteDailyReportList(BaseModel):
    items: list[SiteDailyReportRead]


class HeartbeatRequest(BaseModel):
    status: Literal["provisioning", "ready", "blocked", "offline"] | None = None
    observed_egress_ip: str | None = None


class HeartbeatResponse(BaseModel):
    instance_id: int
    status: str
    last_heartbeat_at: datetime
    observed_egress_ip: str | None = None


class CollectorRuntimeConfigResponse(BaseModel):
    control_plane_base_url: str
    instance_id: int
    account_id: int
    expected_egress_ip: str
    proxy_protocol: Literal["http", "https", "socks5"]
    proxy_host: str
    proxy_port: int
    proxy_username: str | None = None
    proxy_password: str | None = None
    egress_check_url: str
    request_timeout_seconds: int
    google: CollectorGoogleRuntimeCredentials


class TaskStatusUpdate(BaseModel):
    status: Literal["in_progress", "succeeded", "failed", "cancelled", "blocked"]
    message: str | None = None


class BatchIngestionRequest(BaseModel):
    batch_key: str
    row_count: int = 0
    payload_hash: str | None = None
    schema_version: str | None = None
    rows: list[dict[str, Any]] | None = None


class BatchIngestionResponse(ORMModel):
    id: int
    task_id: int
    account_id: int
    batch_key: str
    row_count: int
    payload_hash: str | None
    schema_version: str | None = None
    duplicate: bool = False
