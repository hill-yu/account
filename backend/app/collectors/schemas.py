from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AccountCreate(BaseModel):
    name: str
    status: Literal["pending", "active", "disabled"] = "pending"
    external_account_id: str | None = None
    currency: str = "USD"


class AccountRead(ORMModel):
    id: int
    name: str
    status: str
    external_account_id: str | None
    timezone: str
    currency: str
    created_at: datetime
    updated_at: datetime


class AccountList(BaseModel):
    items: list[AccountRead]


class AccountTimezoneUpdate(BaseModel):
    timezone: str


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
    flow_status: str
    runtime_status: str
    active_credential_version: int | None
    pending_credential_version: int | None
    credential_fingerprint: str | None = None
    failure_class: str | None
    failure_count: int
    last_verified_at: datetime | None
    revoked_at: datetime | None
    publishing_status: str
    next_action: str | None
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


class AuthorizationUrlRequest(BaseModel):
    force_reauthorize: bool = False
    reason: str | None = None


class OAuthCallbackResponse(BaseModel):
    oauth_app_id: int
    account_id: int
    authorization_status: str
    refresh_token_present: bool


class OAuthCredentialAckRequest(BaseModel):
    task_id: int
    account_id: int
    credential_version: int
    token_fingerprint: str
    network_code: str
    network_timezone: str
    granted_scopes: str


class OAuthCredentialAckResponse(BaseModel):
    account_id: int
    credential_version: int
    status: Literal["activated"]
    health_task_id: int


class OAuthCallbackImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: str
    code: str
    redirect_uri: str
    callback_url: str
    scope: str | None = None
    iss: str | None = None
    error: str | None = None
    downloaded_at: datetime | None = None


class CollectorGoogleRuntimeCredentials(BaseModel):
    fetch_mode: Literal["stub", "admanager_rest", "admanager_soap"]
    operation: Literal["fetch", "oauth_credential_validate", "oauth_health_check"] = "fetch"
    credential_version: int | None = None
    credential_fingerprint: str | None = None
    granted_scopes: str | None = None
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
    report_base_url: str | None = None
    report_account_key: str | None = None
    report_token: str | None = None


class InstanceRead(ORMModel):
    id: int
    account_id: int
    name: str
    status: str
    expected_egress_ip: str | None
    report_base_url: str | None
    report_account_key: str | None
    report_token_present: bool
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


class FetchScheduleCreate(BaseModel):
    account_id: int
    collector_instance_id: int
    enabled: bool = True
    mode: Literal["daily_times", "interval_hours"]
    daily_times: list[str] | None = None
    interval_hours: int | None = None
    timezone: str

    @model_validator(mode="after")
    def validate_mode_settings(self) -> "FetchScheduleCreate":
        if self.mode == "daily_times":
            if not self.daily_times:
                raise ValueError("daily_times is required for daily_times mode")
            if self.interval_hours is not None:
                raise ValueError("interval_hours must be empty for daily_times mode")
        if self.mode == "interval_hours":
            if self.interval_hours is None:
                raise ValueError("interval_hours is required for interval_hours mode")
            if self.daily_times is not None:
                raise ValueError("daily_times must be empty for interval_hours mode")
        return self


class FetchScheduleUpdate(BaseModel):
    enabled: bool | None = None
    mode: Literal["daily_times", "interval_hours"] | None = None
    daily_times: list[str] | None = None
    interval_hours: int | None = None
    timezone: str | None = None

    @model_validator(mode="after")
    def validate_mode_settings(self) -> "FetchScheduleUpdate":
        if self.mode == "daily_times":
            if not self.daily_times:
                raise ValueError("daily_times is required for daily_times mode")
            if self.interval_hours is not None:
                raise ValueError("interval_hours must be empty for daily_times mode")
        elif self.mode == "interval_hours":
            if self.interval_hours is None:
                raise ValueError("interval_hours is required for interval_hours mode")
            if self.daily_times is not None:
                raise ValueError("daily_times must be empty for interval_hours mode")
        return self


class FetchScheduleRead(ORMModel):
    id: int
    account_id: int
    collector_instance_id: int
    enabled: bool
    mode: Literal["daily_times", "interval_hours"]
    daily_times: list[str] | None
    interval_hours: int | None
    timezone: str
    last_triggered_at: datetime | None
    next_run_at: datetime | None
    last_trigger_status: str | None
    last_trigger_message: str | None
    created_at: datetime
    updated_at: datetime


class FetchScheduleList(BaseModel):
    items: list[FetchScheduleRead]


class ManualFetchRequest(BaseModel):
    account_id: int
    collector_instance_id: int
    report_date: date


class ManualFetchResponse(BaseModel):
    ok: bool
    status: str | None = None
    run_id: int | None = None
    request_id: str | None = None
    message: str | None = None
    hourly_sync_task_id: int | None = None
    hourly_sync_task_status: str | None = None
    hourly_sync_task_created: bool = False


class HourlyCoverage(BaseModel):
    account_id: int
    report_date: date
    hours_present: list[int]
    hour_count: int
    min_hour: int | None = None
    max_hour: int | None = None
    is_complete_day: bool
    latest_task_id: int | None = None
    # --- 值级校验: 小时聚合 vs 日报表 ---
    daily_revenue: float | None = None
    hourly_revenue: float | None = None
    revenue_diff_percent: float | None = None
    daily_impressions: int | None = None
    hourly_impressions: int | None = None
    impressions_diff_percent: float | None = None
    is_value_match: bool | None = None  # None = 无法对比（日报不存在），True = 一致，False = 不一致


class AccountDailyReportRead(ORMModel):
    id: int
    account_id: int
    report_date: date
    responses_served: int
    requests: int
    impressions: int
    clicks: int
    revenue: float
    ecpm: float
    created_at: datetime
    updated_at: datetime


class AccountDailyReportList(BaseModel):
    timezone: str
    coverage: HourlyCoverage | None = None
    items: list[AccountDailyReportRead]


class AccountHourlyReportRead(ORMModel):
    id: int
    account_id: int
    report_date: date
    hour: int
    report_time_utc: datetime
    source_timezone: str
    currency: str
    ad_country_code: str
    ad_country_name: str
    ad_slot_id: str
    ad_slot_name: str
    responses_served: int
    requests: int
    impressions: int
    clicks: int
    revenue: float
    ecpm: float
    created_at: datetime
    updated_at: datetime


class AccountHourlyReportList(BaseModel):
    timezone: str
    items: list[AccountHourlyReportRead]


class SiteDailyReportRead(ORMModel):
    id: int
    account_id: int
    report_date: date
    url_id: str
    url: str
    responses_served: int
    requests: int
    impressions: int
    clicks: int
    revenue: float
    ecpm: float
    created_at: datetime
    updated_at: datetime


class SiteDailyReportList(BaseModel):
    timezone: str
    coverage: HourlyCoverage | None = None
    items: list[SiteDailyReportRead]


class SiteHourlyReportRead(ORMModel):
    id: int
    account_id: int
    report_date: date
    hour: int
    report_time_utc: datetime
    source_timezone: str
    currency: str
    url_id: str
    url: str
    ad_country_code: str
    ad_country_name: str
    ad_slot_id: str
    ad_slot_name: str
    responses_served: int
    requests: int
    impressions: int
    clicks: int
    revenue: float
    ecpm: float
    created_at: datetime
    updated_at: datetime


class SiteHourlyReportList(BaseModel):
    timezone: str
    items: list[SiteHourlyReportRead]


class TargetedHourlyBackfillRequest(BaseModel):
    anchor_date: date | None = None
    days: int = Field(default=4, ge=1, le=14)
    account_keys: list[str] | None = None


class TargetedHourlyBackfillItem(BaseModel):
    account_id: int
    account_key: str
    collector_instance_id: int
    report_date: date
    hourly_sync_task_id: int
    hourly_sync_task_status: str
    hourly_sync_task_created: bool


class TargetedHourlyBackfillResponse(BaseModel):
    anchor_date: date
    days: int
    requested_account_keys: list[str]
    items: list[TargetedHourlyBackfillItem]


class MidPlatformLinkResource(BaseModel):
    account_id: int
    account_name: str
    instance_id: int
    instance_name: str
    node_base_url: str
    node_account_key: str
    site_name: str
    link_key: str
    link_name: str
    destination_url: str | None = None
    currency: str = "USD"
    default_display_timezone: str = "America/Los_Angeles"
    status: Literal["active", "disabled"] = "active"


class MidPlatformLinkResourceListResponse(BaseModel):
    items: list[MidPlatformLinkResource]


class MidPlatformAccountResource(BaseModel):
    account_id: int
    account_name: str
    external_account_key: str
    network_code: str | None = None
    timezone: str = "America/Los_Angeles"
    default_display_timezone: str = "America/Los_Angeles"
    currency: str = "USD"
    status: Literal["active", "disabled"] = "active"


class MidPlatformAccountResourceListResponse(BaseModel):
    items: list[MidPlatformAccountResource]


class MidPlatformNodeResource(BaseModel):
    account_id: int
    account_name: str
    instance_id: int
    instance_name: str
    node_base_url: str
    node_account_key: str
    currency: str = "USD"
    default_display_timezone: str = "America/Los_Angeles"
    status: Literal["active", "disabled"] = "active"


class MidPlatformNodeResourceListResponse(BaseModel):
    items: list[MidPlatformNodeResource]


class MidPlatformSiteResource(BaseModel):
    account_id: int
    account_name: str
    instance_id: int
    instance_name: str
    node_base_url: str
    node_account_key: str
    site_name: str
    currency: str = "USD"
    default_display_timezone: str = "America/Los_Angeles"
    status: Literal["active", "disabled"] = "active"


class MidPlatformSiteResourceListResponse(BaseModel):
    items: list[MidPlatformSiteResource]


class MidPlatformNodeResult(BaseModel):
    account_id: int
    account_name: str
    instance_id: int
    instance_name: str
    node_base_url: str
    node_account_key: str
    source_state: Literal["success", "no_snapshot", "error"]
    source_http_status: int | None = None
    source_run_id: int | None = None
    row_count: int = 0
    message: str | None = None


class MidPlatformSummary(BaseModel):
    report_date: date
    requested_node_count: int
    success_node_count: int
    no_snapshot_node_count: int
    error_node_count: int
    row_count: int
    total_responses_served: int
    total_requests: int
    total_impressions: int
    total_clicks: int
    total_revenue: float


class MidPlatformSiteDailyRow(BaseModel):
    account_id: int
    account_name: str
    instance_id: int
    instance_name: str
    node_base_url: str
    node_account_key: str
    report_date: date
    site_name: str
    responses_served: int
    requests: int
    impressions: int
    clicks: int
    revenue: float
    ecpm: float
    source_run_id: int | None = None


class MidPlatformSiteDailyReportResponse(BaseModel):
    report_date: date
    timezone: str
    summary: MidPlatformSummary
    node_results: list[MidPlatformNodeResult]
    items: list[MidPlatformSiteDailyRow]


class MidPlatformSiteHourlyRow(BaseModel):
    account_id: int
    account_name: str
    instance_id: int
    instance_name: str
    node_base_url: str
    node_account_key: str
    report_date: date
    hour: int
    report_time_utc: datetime
    source_timezone: str
    currency: str
    site_name: str
    ad_country_code: str
    ad_country_name: str
    ad_slot_id: str
    ad_slot_name: str
    responses_served: int
    requests: int
    impressions: int
    clicks: int
    revenue: float
    ecpm: float
    source_run_id: int | None = None


class MidPlatformSiteHourlyReportResponse(BaseModel):
    report_date: date
    timezone: str
    items: list[MidPlatformSiteHourlyRow]


class MidPlatformAccountDailyRow(BaseModel):
    account_id: int
    account_name: str
    instance_id: int
    instance_name: str
    node_base_url: str
    node_account_key: str
    report_date: date
    site_count: int
    responses_served: int
    requests: int
    impressions: int
    clicks: int
    revenue: float
    ecpm: float
    source_run_id: int | None = None


class MidPlatformAccountDailyReportResponse(BaseModel):
    report_date: date
    timezone: str
    summary: MidPlatformSummary
    node_results: list[MidPlatformNodeResult]
    items: list[MidPlatformAccountDailyRow]


class MidPlatformAccountHourlyRow(BaseModel):
    account_id: int
    account_name: str
    instance_id: int
    instance_name: str
    node_base_url: str
    node_account_key: str
    report_date: date
    hour: int
    report_time_utc: datetime
    source_timezone: str
    currency: str
    ad_country_code: str
    ad_country_name: str
    ad_slot_id: str
    ad_slot_name: str
    responses_served: int
    requests: int
    impressions: int
    clicks: int
    revenue: float
    ecpm: float
    source_run_id: int | None = None


class MidPlatformAccountHourlyReportResponse(BaseModel):
    report_date: date
    timezone: str
    items: list[MidPlatformAccountHourlyRow]


class MidPlatformLinkDailyRow(BaseModel):
    account_id: int
    account_name: str
    instance_id: int
    instance_name: str
    node_base_url: str
    node_account_key: str
    report_date: date
    site_name: str
    link_key: str
    responses_served: int
    requests: int
    impressions: int
    clicks: int
    revenue: float
    ecpm: float
    source_run_id: int | None = None


class MidPlatformLinkDailyReportResponse(BaseModel):
    report_date: date
    timezone: str
    summary: MidPlatformSummary
    node_results: list[MidPlatformNodeResult]
    items: list[MidPlatformLinkDailyRow]


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
    failure_class: str | None = None


class BatchIngestionRequest(BaseModel):
    batch_key: str
    row_count: int = 0
    payload_hash: str | None = None
    schema_version: str | None = None
    merge_mode: str | None = None
    touched_hours: list[int] | None = None
    expected_hour_count: int | None = None
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
