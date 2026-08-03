import type {
  AccountCreate,
  AccountDailyReportList,
  AccountList,
  AuthorizationUrlRequest,
  AuthorizationUrlResponse,
  FetchScheduleCreate,
  FetchScheduleList,
  FetchScheduleRead,
  FetchScheduleUpdate,
  InstanceCreate,
  InstanceList,
  InstanceProvisionResponse,
  ManualFetchRequest,
  ManualFetchResponse,
  MidPlatformAccountDailyReportResponse,
  MidPlatformSiteDailyReportResponse,
  OAuthCallbackImportRequest,
  OAuthCallbackResponse,
  OAuthAppCreate,
  OAuthAppList,
  ProxyBindingCreate,
  ProxyBindingList,
  SiteDailyReportList,
  SyncTaskCreate,
  SyncTaskList,
} from "../types/api";

export interface ApiError extends Error {
  status?: number;
  detail?: string;
}

export interface OperatorSession {
  authenticated: boolean;
}

function resolveApiBaseUrl(): string {
  const configuredBaseUrl = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "");
  if (configuredBaseUrl) {
    return configuredBaseUrl;
  }

  if (typeof window === "undefined") {
    return "http://127.0.0.1:8000";
  }

  const { hostname, origin } = window.location;
  if (hostname === "localhost" || hostname === "127.0.0.1") {
    return "http://127.0.0.1:8000";
  }

  return origin;
}

const API_BASE_URL = resolveApiBaseUrl();

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    credentials: init?.credentials ?? "include",
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });

  if (!response.ok) {
    let detail = "";
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") {
        detail = body.detail;
      } else if (Array.isArray(body?.detail)) {
        detail = "Validation error";
      }
    } catch {
      detail = "";
    }

    const error = new Error(detail || response.statusText) as ApiError;
    error.status = response.status;
    error.detail = detail || response.statusText;
    throw error;
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export const api = {
  getOperatorSession: () => request<OperatorSession>("/api/v1/operator/auth/session"),
  loginOperator: (password: string) =>
    request<OperatorSession>("/api/v1/operator/auth/login", {
      method: "POST",
      body: JSON.stringify({ password }),
    }),
  logoutOperator: () => request<void>("/api/v1/operator/auth/logout", { method: "POST" }),
  listAccounts: () => request<AccountList>("/api/v1/operator/accounts"),
  createAccount: (payload: AccountCreate) =>
    request("/api/v1/operator/accounts", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  listOAuthApps: () => request<OAuthAppList>("/api/v1/operator/oauth-apps"),
  createOAuthApp: (payload: OAuthAppCreate) =>
    request("/api/v1/operator/oauth-apps", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  generateAuthorizationUrl: (oauthAppId: number, payload?: AuthorizationUrlRequest) =>
    request<AuthorizationUrlResponse>(`/api/v1/operator/oauth-apps/${oauthAppId}/authorization-url`, {
      method: "POST",
      body: payload ? JSON.stringify(payload) : undefined,
    }),
  completeOAuthCallback: (state: string, code: string) =>
    request<OAuthCallbackResponse>(
      `/api/v1/oauth/google/callback?state=${encodeURIComponent(state)}&code=${encodeURIComponent(code)}`,
    ),
  importOAuthCallbackJson: (payload: OAuthCallbackImportRequest) =>
    request<OAuthCallbackResponse>("/api/v1/operator/oauth-apps/import-callback-json", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  listInstances: () => request<InstanceList>("/api/v1/operator/instances"),
  createInstance: (payload: InstanceCreate) =>
    request<InstanceProvisionResponse>("/api/v1/operator/instances", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  listProxies: () => request<ProxyBindingList>("/api/v1/operator/proxies"),
  createProxy: (payload: ProxyBindingCreate) =>
    request("/api/v1/operator/proxies", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  listTasks: () => request<SyncTaskList>("/api/v1/operator/tasks"),
  createTask: (payload: SyncTaskCreate) =>
    request("/api/v1/operator/tasks", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  listFetchSchedules: () => request<FetchScheduleList>("/api/v1/operator/fetch-schedules"),
  createFetchSchedule: (payload: FetchScheduleCreate) =>
    request<FetchScheduleRead>("/api/v1/operator/fetch-schedules", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateFetchSchedule: (scheduleId: number, payload: FetchScheduleUpdate) =>
    request<FetchScheduleRead>(`/api/v1/operator/fetch-schedules/${scheduleId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  triggerManualFetch: (payload: ManualFetchRequest) =>
    request<ManualFetchResponse>("/api/v1/operator/fetch-schedules/manual-fetch", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  listSiteDailyReports: (accountId?: number, reportDate?: string) => {
    const params = new URLSearchParams();
    if (accountId) {
      params.set("account_id", String(accountId));
    }
    if (reportDate) {
      params.set("report_date", reportDate);
    }
    return request<SiteDailyReportList>(`/api/v1/operator/reports/site-daily${params.size ? `?${params}` : ""}`);
  },
  listAccountDailyReports: (accountId?: number, reportDate?: string) => {
    const params = new URLSearchParams();
    if (accountId) {
      params.set("account_id", String(accountId));
    }
    if (reportDate) {
      params.set("report_date", reportDate);
    }
    return request<AccountDailyReportList>(`/api/v1/operator/reports/account-daily${params.size ? `?${params}` : ""}`);
  },
  listMidPlatformSiteDailyReports: (accountId?: number, reportDate?: string) => {
    const params = new URLSearchParams();
    if (accountId) {
      params.set("account_id", String(accountId));
    }
    if (reportDate) {
      params.set("report_date", reportDate);
    }
    return request<MidPlatformSiteDailyReportResponse>(
      `/api/v1/operator/mid-platform/reports/site-daily${params.size ? `?${params}` : ""}`,
    );
  },
  listMidPlatformAccountDailyReports: (accountId?: number, reportDate?: string) => {
    const params = new URLSearchParams();
    if (accountId) {
      params.set("account_id", String(accountId));
    }
    if (reportDate) {
      params.set("report_date", reportDate);
    }
    return request<MidPlatformAccountDailyReportResponse>(
      `/api/v1/operator/mid-platform/reports/account-daily${params.size ? `?${params}` : ""}`,
    );
  },
};
