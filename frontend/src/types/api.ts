export type AccountStatus = "pending" | "active" | "disabled";
export type AppStatus = "pending" | "active" | "disabled";
export type VerificationStatus = "pending" | "verified" | "rejected";
export type AuthorizationStatus = "pending" | "authorized" | "expired" | "revoked" | "failed";
export type InstanceStatus = "provisioning" | "ready" | "blocked" | "offline";
export type ProxyStatus = "active" | "disabled" | "error";
export type SyncTaskStatus = "pending" | "in_progress" | "succeeded" | "failed" | "cancelled" | "blocked";
export type ProxyProtocol = "http" | "https" | "socks5";

export interface AccountRead {
  id: number;
  name: string;
  status: AccountStatus | string;
  external_account_id: string | null;
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

export interface OAuthCallbackResponse {
  oauth_app_id: number;
  account_id: number;
  authorization_status: string;
  refresh_token_present: boolean;
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

export interface SiteDailyReportRead {
  id: number;
  account_id: number;
  report_date: string;
  url_id: string;
  url: string;
  responses_served: number;
  impressions: number;
  clicks: number;
  revenue: number;
  ecpm: number;
  created_at: string;
  updated_at: string;
}

export interface SiteDailyReportList {
  items: SiteDailyReportRead[];
}

export interface AccountDailyReportRead {
  id: number;
  account_id: number;
  report_date: string;
  responses_served: number;
  impressions: number;
  clicks: number;
  revenue: number;
  ecpm: number;
  created_at: string;
  updated_at: string;
}

export interface AccountDailyReportList {
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
  summary: MidPlatformSummary;
  node_results: MidPlatformNodeResult[];
  items: MidPlatformAccountDailyRow[];
}
