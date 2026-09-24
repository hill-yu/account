export type AccountStatus = "pending" | "active" | "disabled";
export type AppStatus = "pending" | "active" | "disabled";
export type VerificationStatus = "pending" | "verified" | "rejected";
export type AuthorizationStatus = "pending" | "authorized" | "expired" | "revoked" | "failed";
export type OAuthFlowStatus = "pending" | "requested" | "validation_pending" | "completed" | "exchange_failed";
export type OAuthRuntimeStatus = "unknown" | "healthy" | "degraded" | "revoked" | "policy_blocked" | "migration_required";
export type InstanceStatus = "provisioning" | "ready" | "blocked" | "offline";
export type ProxyStatus = "active" | "disabled" | "error";
export type SyncTaskStatus = "pending" | "in_progress" | "succeeded" | "failed" | "cancelled" | "blocked";
export type ProxyProtocol = "http" | "https" | "socks5";
export type FetchScheduleMode = "daily_times" | "interval_hours";

export interface AccountRead {
  id: number;
  name: string;
  status: AccountStatus | string;
  external_account_id: string | null;
  timezone: string;
  created_at: string;
  updated_at: string;
}

export interface AccountList {
  items: AccountRead[];
}

export interface AccountCreate {
  name: string;
  status: AccountStatus;
  external_account_id: string | null;
}

export interface OAuthAppRead {
  id: number;
  account_id: number;
  client_id: string;
  redirect_uri: string;
  scopes: string;
  app_status: AppStatus | string;
  verification_status: VerificationStatus | string;
  authorization_status: AuthorizationStatus | string;
  flow_status: OAuthFlowStatus | string;
  runtime_status: OAuthRuntimeStatus | string;
  active_credential_version: number | null;
  pending_credential_version: number | null;
  credential_fingerprint: string | null;
  failure_class: string | null;
  failure_count: number;
  last_verified_at: string | null;
  revoked_at: string | null;
  publishing_status: string;
  next_action: string | null;
  authorization_requested_at: string | null;
  authorization_completed_at: string | null;
  access_token_expires_at: string | null;
  refresh_token_updated_at: string | null;
  granted_scopes: string | null;
  refresh_token_present: boolean;
  created_at: string;
  updated_at: string;
}

export interface OAuthAppList {
  items: OAuthAppRead[];
}

export interface OAuthAppCreate {
  account_id: number;
  client_id: string;
  client_secret: string;
  redirect_uri: string;
  scopes: string;
  app_status: AppStatus;
  verification_status: VerificationStatus;
}

export interface AuthorizationUrlResponse {
  authorization_url: string;
  state: string;
  state_expires_at: string;
}

export interface AuthorizationUrlRequest {
  force_reauthorize?: boolean;
  reason?: string | null;
}

export interface OAuthCallbackResponse {
  oauth_app_id: number;
  account_id: number;
  authorization_status: string;
  refresh_token_present: boolean;
}

export interface OAuthCallbackImportRequest {
  state: string;
  code: string;
  redirect_uri: string;
  callback_url: string;
  scope?: string | null;
  iss?: string | null;
  error?: string | null;
  downloaded_at?: string | null;
}

export interface InstanceRead {
  id: number;
  account_id: number;
  name: string;
  status: InstanceStatus | string;
  expected_egress_ip: string | null;
  report_base_url: string | null;
  report_account_key: string | null;
  report_token_present: boolean;
  last_heartbeat_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface InstanceProvisionResponse extends InstanceRead {
  instance_token: string;
}

export interface InstanceList {
  items: InstanceRead[];
}

export interface InstanceCreate {
  account_id: number;
  name: string;
  status: InstanceStatus;
  expected_egress_ip: string | null;
  report_base_url?: string | null;
  report_account_key?: string | null;
  report_token?: string | null;
}

export interface ProxyBindingRead {
  id: number;
  account_id: number;
  collector_instance_id: number;
  provider_name: string;
  protocol: ProxyProtocol | string;
  host: string;
  port: number;
  username: string | null;
  password: string | null;
  expected_egress_ip: string;
  status: ProxyStatus | string;
  created_at: string;
  updated_at: string;
}

export interface ProxyBindingList {
  items: ProxyBindingRead[];
}

export interface ProxyBindingCreate {
  account_id: number;
  collector_instance_id: number;
  provider_name: string;
  protocol: ProxyProtocol;
  host: string;
  port: number;
  username: string | null;
  password: string | null;
  expected_egress_ip: string;
  status: ProxyStatus;
}

export interface SyncTaskRead {
  id: number;
  account_id: number;
  collector_instance_id: number;
  task_type: string;
  report_date: string;
  status: SyncTaskStatus | string;
  external_request_id: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface SyncTaskList {
  items: SyncTaskRead[];
}

export interface SyncTaskCreate {
  account_id: number;
  collector_instance_id: number;
  task_type: string;
  report_date: string;
  status: SyncTaskStatus;
  external_request_id: string | null;
}

export interface FetchScheduleRead {
  id: number;
  account_id: number;
  collector_instance_id: number;
  enabled: boolean;
  mode: FetchScheduleMode;
  daily_times: string[] | null;
  interval_hours: number | null;
  timezone: string;
  last_triggered_at: string | null;
  next_run_at: string | null;
  last_trigger_status: string | null;
  last_trigger_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface FetchScheduleList {
  items: FetchScheduleRead[];
}

export interface FetchScheduleCreate {
  account_id: number;
  collector_instance_id: number;
  enabled: boolean;
  mode: FetchScheduleMode;
  daily_times: string[] | null;
  interval_hours: number | null;
  timezone: string;
}

export interface FetchScheduleUpdate {
  enabled?: boolean;
  mode?: FetchScheduleMode;
  daily_times?: string[] | null;
  interval_hours?: number | null;
  timezone?: string;
}

export interface ManualFetchRequest {
  account_id: number;
  collector_instance_id: number;
  report_date: string;
}

export interface ManualFetchResponse {
  ok: boolean;
  status: string | null;
  run_id: number | null;
  request_id: string | null;
  message: string | null;
  hourly_sync_task_id: number | null;
  hourly_sync_task_status: string | null;
  hourly_sync_task_created: boolean;
}

export interface SiteDailyReportRead {
  id: number;
  account_id: number;
  report_date: string;
  url_id: string;
  url: string;
  responses_served: number;
  requests: number;
  impressions: number;
  clicks: number;
  revenue: number;
  ecpm: number;
  created_at: string;
  updated_at: string;
}

export interface SiteDailyReportList {
  timezone: string;
  items: SiteDailyReportRead[];
}

export interface AccountDailyReportRead {
  id: number;
  account_id: number;
  report_date: string;
  responses_served: number;
  requests: number;
  impressions: number;
  clicks: number;
  revenue: number;
  ecpm: number;
  created_at: string;
  updated_at: string;
}

export interface AccountDailyReportList {
  timezone: string;
  items: AccountDailyReportRead[];
}

export type MidPlatformNodeState = "success" | "no_snapshot" | "error";

export interface MidPlatformSummary {
  report_date: string;
  requested_node_count: number;
  success_node_count: number;
  no_snapshot_node_count: number;
  error_node_count: number;
  row_count: number;
  total_responses_served: number;
  total_impressions: number;
  total_clicks: number;
  total_revenue: number;
}

export interface MidPlatformNodeResult {
  account_id: number;
  account_name: string;
  instance_id: number;
  instance_name: string;
  node_base_url: string;
  node_account_key: string;
  source_state: MidPlatformNodeState;
  source_http_status: number | null;
  source_run_id: number | null;
  row_count: number;
  message: string | null;
}

export interface MidPlatformSiteDailyRow {
  account_id: number;
  account_name: string;
  instance_id: number;
  instance_name: string;
  node_base_url: string;
  node_account_key: string;
  report_date: string;
  site_name: string;
  responses_served: number;
  impressions: number;
  clicks: number;
  revenue: number;
  ecpm: number;
  source_run_id: number;
}

export interface MidPlatformSiteDailyReportResponse {
  report_date: string;
  timezone: string;
  summary: MidPlatformSummary;
  node_results: MidPlatformNodeResult[];
  items: MidPlatformSiteDailyRow[];
}

export interface MidPlatformAccountDailyRow {
  account_id: number;
  account_name: string;
  instance_id: number;
  instance_name: string;
  node_base_url: string;
  node_account_key: string;
  report_date: string;
  site_count: number;
  responses_served: number;
  impressions: number;
  clicks: number;
  revenue: number;
  ecpm: number;
  source_run_id: number;
}

export interface MidPlatformAccountDailyReportResponse {
  report_date: string;
  timezone: string;
  summary: MidPlatformSummary;
  node_results: MidPlatformNodeResult[];
  items: MidPlatformAccountDailyRow[];
}
