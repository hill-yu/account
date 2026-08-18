import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ToastContext, type ToastInput } from "../components/ui/useToast";
import { api } from "../lib/api";
import { OperationsPage } from "../pages/OperationsPage";
import type { AccountRead, InstanceRead, OAuthAppRead, SyncTaskRead } from "../types/api";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

type Deferred<T> = {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason: unknown) => void;
};

type PaginatedApi = typeof api & {
  listTasksPaged: (page?: number, pageSize?: number, snapshotMaxId?: number) => Promise<{
    items: SyncTaskRead[];
    page: number;
    page_size: number;
    total: number;
    snapshot_max_id: number;
  }>;
};

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

const account = (id: number, name: string): AccountRead => ({
  id,
  name,
  status: "active",
  external_account_id: null,
  timezone: "Asia/Shanghai",
  created_at: "2026-08-18T00:00:00Z",
  updated_at: "2026-08-18T00:00:00Z",
});

const instance = (id: number): InstanceRead => ({
  id,
  account_id: 1,
  name: `instance-${id}`,
  status: "ready",
  expected_egress_ip: null,
  report_base_url: null,
  report_account_key: null,
  report_token_present: false,
  last_heartbeat_at: null,
  created_at: "2026-08-18T00:00:00Z",
  updated_at: "2026-08-18T00:00:00Z",
});

const oauthApp = (id: number): OAuthAppRead => ({
  id,
  account_id: 1,
  client_id: `client-${id}`,
  redirect_uri: "https://example.test/oauth/google/callback",
  scopes: "scope",
  app_status: "active",
  verification_status: "verified",
  authorization_status: "authorized",
  flow_status: "completed",
  runtime_status: "healthy",
  active_credential_version: 1,
  pending_credential_version: null,
  credential_fingerprint: "abcdef123456",
  failure_class: null,
  failure_count: 0,
  last_verified_at: null,
  revoked_at: null,
  publishing_status: "testing",
  next_action: null,
  authorization_requested_at: null,
  authorization_completed_at: null,
  access_token_expires_at: null,
  refresh_token_updated_at: null,
  granted_scopes: null,
  refresh_token_present: true,
  created_at: "2026-08-18T00:00:00Z",
  updated_at: "2026-08-18T00:00:00Z",
});

const task = (id: number): SyncTaskRead => ({
  id,
  account_id: 1,
  collector_instance_id: 1,
  task_type: "report_fetch",
  report_date: "2026-08-18",
  status: "succeeded",
  external_request_id: null,
  started_at: null,
  finished_at: null,
  created_at: "2026-08-18T00:00:00Z",
  updated_at: "2026-08-18T00:00:00Z",
});

describe("OperationsPage progressive loading", () => {
  let container: HTMLDivElement;
  let root: Root;
  let pushToast: ReturnType<typeof vi.fn<(input: ToastInput) => void>>;
  let originalListTasksPagedDescriptor: PropertyDescriptor | undefined;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    pushToast = vi.fn<(input: ToastInput) => void>();

    vi.spyOn(api, "listAccounts").mockResolvedValue({ items: [account(1, "cached-account")] });
    vi.spyOn(api, "listOAuthApps").mockResolvedValue({ items: [] });
    vi.spyOn(api, "listInstances").mockResolvedValue({ items: [instance(1)] });
    vi.spyOn(api, "listProxies").mockResolvedValue({ items: [] });
    vi.spyOn(api, "listFetchSchedules").mockResolvedValue({ items: [] });
    vi.spyOn(api, "listTasks").mockResolvedValue({ items: [] });
    originalListTasksPagedDescriptor = Object.getOwnPropertyDescriptor(api, "listTasksPaged");
    const apiWithPagination = api as PaginatedApi;
    apiWithPagination.listTasksPaged = vi.fn().mockResolvedValue({
      items: [], page: 1, page_size: 100, total: 0, snapshot_max_id: 0,
    });
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.restoreAllMocks();
    if (originalListTasksPagedDescriptor) {
      Object.defineProperty(api, "listTasksPaged", originalListTasksPagedDescriptor);
    } else {
      Reflect.deleteProperty(api, "listTasksPaged");
    }
  });

  async function renderPage() {
    await act(async () => {
      root.render(
        <ToastContext.Provider value={{ pushToast }}>
          <OperationsPage />
        </ToastContext.Provider>,
      );
      await Promise.resolve();
    });
  }

  async function clickButton(label: string) {
    const match = findButton((text) => text === label);
    await act(async () => {
      match.click();
      await Promise.resolve();
    });
  }

  function findButton(matches: (text: string) => boolean): HTMLButtonElement {
    const match = [...container.querySelectorAll("button")].find((item) => matches(item.textContent?.trim() ?? ""));
    if (!(match instanceof HTMLButtonElement)) throw new Error("Matching button not found");
    return match;
  }

  async function choose(select: HTMLSelectElement, value: string) {
    await act(async () => {
      select.value = value;
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
  }

  const pagedTasks = () => (api as PaginatedApi & { listTasksPaged: ReturnType<typeof vi.fn> }).listTasksPaged;

  it("loads only Accounts on first render and reuses it when OAuth is opened", async () => {
    await renderPage();

    expect(api.listAccounts).toHaveBeenCalledTimes(1);
    expect(api.listOAuthApps).not.toHaveBeenCalled();
    expect(api.listInstances).not.toHaveBeenCalled();
    expect(api.listProxies).not.toHaveBeenCalled();
    expect(api.listFetchSchedules).not.toHaveBeenCalled();
    expect(api.listTasks).not.toHaveBeenCalled();
    expect(pagedTasks()).not.toHaveBeenCalled();

    await clickButton("OAuth Apps");
    expect(api.listAccounts).toHaveBeenCalledTimes(1);
    expect(api.listOAuthApps).toHaveBeenCalledTimes(1);
    expect(api.listTasks).not.toHaveBeenCalled();
    expect(pagedTasks()).not.toHaveBeenCalled();

    await clickButton("Accounts");
    expect(api.listAccounts).toHaveBeenCalledTimes(1);
  });

  it("keeps a successful account cache and retries only a failed OAuth dependency", async () => {
    vi.mocked(api.listOAuthApps).mockRejectedValueOnce(new Error("oauth unavailable")).mockResolvedValueOnce({ items: [] });
    await renderPage();
    await clickButton("OAuth Apps");

    expect(container.textContent).toContain("cached-account");
    expect(api.listAccounts).toHaveBeenCalledTimes(1);
    expect(api.listOAuthApps).toHaveBeenCalledTimes(1);

    await clickButton("Accounts");
    await clickButton("OAuth Apps");
    expect(api.listAccounts).toHaveBeenCalledTimes(1);
    expect(api.listOAuthApps).toHaveBeenCalledTimes(2);
  });

  it("commits OAuth success independently and retries only Accounts after the reverse partial failure", async () => {
    const pendingAccounts = deferred<{ items: AccountRead[] }>();
    const pendingOAuth = deferred<{ items: OAuthAppRead[] }>();
    vi.mocked(api.listAccounts).mockReturnValueOnce(pendingAccounts.promise).mockResolvedValueOnce({ items: [account(1, "recovered")] });
    vi.mocked(api.listOAuthApps).mockReturnValue(pendingOAuth.promise);

    await renderPage();
    await clickButton("OAuth Apps");
    await act(async () => pendingOAuth.resolve({ items: [oauthApp(9)] }));
    await act(async () => pendingAccounts.reject(new Error("accounts unavailable")));

    expect(container.textContent).toContain("client-9");
    expect(api.listOAuthApps).toHaveBeenCalledTimes(1);
    expect(api.listInstances).not.toHaveBeenCalled();
    expect(api.listProxies).not.toHaveBeenCalled();
    expect(api.listFetchSchedules).not.toHaveBeenCalled();
    expect(api.listTasks).not.toHaveBeenCalled();
    expect(pagedTasks()).not.toHaveBeenCalled();

    await clickButton("Accounts");
    await clickButton("OAuth Apps");
    expect(api.listAccounts).toHaveBeenCalledTimes(2);
    expect(api.listOAuthApps).toHaveBeenCalledTimes(1);
  });

  it("force-refreshes every dependency of the active OAuth tab", async () => {
    await renderPage();
    await clickButton("OAuth Apps");
    await clickButton("刷新数据");

    expect(api.listAccounts).toHaveBeenCalledTimes(2);
    expect(api.listOAuthApps).toHaveBeenCalledTimes(2);
    expect(api.listTasks).not.toHaveBeenCalled();
    expect(pagedTasks()).not.toHaveBeenCalled();
  });

  it("deduplicates ordinary tab loads while Accounts is already pending", async () => {
    const pendingAccounts = deferred<{ items: AccountRead[] }>();
    vi.mocked(api.listAccounts).mockReturnValue(pendingAccounts.promise);
    await renderPage();
    await clickButton("OAuth Apps");

    expect(api.listAccounts).toHaveBeenCalledTimes(1);
    expect(api.listInstances).not.toHaveBeenCalled();
    expect(api.listTasks).not.toHaveBeenCalled();
    await act(async () => pendingAccounts.resolve({ items: [account(1, "resolved")] }));
  });

  it("disables refresh while the active resource is loading and prevents concurrent force requests", async () => {
    const refreshRequest = deferred<{ items: AccountRead[] }>();
    vi.mocked(api.listAccounts).mockResolvedValueOnce({ items: [account(1, "loaded")] }).mockReturnValueOnce(refreshRequest.promise);
    await renderPage();
    const refreshButton = findButton((text) => text.startsWith("刷新"));
    await act(async () => refreshButton.click());
    expect(api.listAccounts).toHaveBeenCalledTimes(2);
    expect(refreshButton.disabled).toBe(true);
    await act(async () => refreshButton.click());
    expect(api.listAccounts).toHaveBeenCalledTimes(2);
    await act(async () => refreshRequest.resolve({ items: [account(2, "refreshed")] }));
    expect(refreshButton.disabled).toBe(false);
  });

  it("keeps loaded account data cached when a forced refresh fails", async () => {
    vi.mocked(api.listAccounts).mockResolvedValueOnce({ items: [account(1, "still-cached")] }).mockRejectedValueOnce(new Error("refresh failed"));
    await renderPage();
    await clickButton("刷新数据");
    expect(container.textContent).toContain("still-cached");
    await clickButton("OAuth Apps");
    await clickButton("Accounts");
    expect(api.listAccounts).toHaveBeenCalledTimes(2);
  });

  it("does not report account creation as failed when its list refresh fails", async () => {
    vi.mocked(api.listAccounts).mockResolvedValueOnce({ items: [account(1, "cached")] }).mockRejectedValueOnce(new Error("refresh failed"));
    vi.spyOn(api, "createAccount").mockResolvedValue(account(2, "created"));
    await renderPage();
    const nameInput = container.querySelector('input[required]');
    if (!(nameInput instanceof HTMLInputElement)) throw new Error("Account name input not found");
    await act(async () => {
      nameInput.value = "created";
      nameInput.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await clickButton("Create Account");
    expect(pushToast).toHaveBeenCalledWith(expect.objectContaining({ title: "账号已创建", tone: "success" }));
    expect(pushToast).not.toHaveBeenCalledWith(expect.objectContaining({ title: "创建账号失败" }));
    expect(pushToast).toHaveBeenCalledWith(expect.objectContaining({ title: "加载账户失败", tone: "error" }));
  });

  it("refreshes OAuth Apps after generating an authorization URL", async () => {
    const app = { ...oauthApp(7), runtime_status: "unknown", flow_status: "not_started" };
    vi.mocked(api.listOAuthApps).mockResolvedValueOnce({ items: [app] }).mockResolvedValueOnce({ items: [app] });
    vi.spyOn(api, "generateAuthorizationUrl").mockResolvedValue({ authorization_url: "https://accounts.example/auth", state: "opaque-state", state_expires_at: "2026-08-18T01:00:00Z" });
    await renderPage();
    await clickButton("OAuth Apps");
    await clickButton("Generate URL");
    expect(api.listOAuthApps).toHaveBeenCalledTimes(2);
  });

  it("loads Tasks on first activation, keeps its snapshot across tabs, and refreshes with a new snapshot", async () => {
    pagedTasks()
      .mockResolvedValueOnce({ items: [task(205)], page: 1, page_size: 100, total: 205, snapshot_max_id: 205 })
      .mockResolvedValueOnce({ items: [task(99)], page: 2, page_size: 100, total: 205, snapshot_max_id: 205 })
      .mockResolvedValueOnce({ items: [task(206)], page: 1, page_size: 100, total: 206, snapshot_max_id: 206 });
    await renderPage();
    await clickButton("Tasks");
    expect(pagedTasks()).toHaveBeenNthCalledWith(1, 1, 100, undefined);

    await clickButton("下一页");
    expect(pagedTasks()).toHaveBeenNthCalledWith(2, 2, 100, 205);
    await clickButton("Accounts");
    await clickButton("Tasks");
    expect(pagedTasks()).toHaveBeenCalledTimes(2);

    await clickButton("刷新数据");
    expect(pagedTasks()).toHaveBeenNthCalledWith(3, 1, 100, undefined);
  });

  it("keeps the current Tasks page and snapshot cached when refresh fails", async () => {
    pagedTasks()
      .mockResolvedValueOnce({ items: [task(205)], page: 1, page_size: 100, total: 205, snapshot_max_id: 205 })
      .mockResolvedValueOnce({ items: [task(99)], page: 2, page_size: 100, total: 205, snapshot_max_id: 205 })
      .mockRejectedValueOnce(new Error("refresh failed"));
    await renderPage();
    await clickButton("Tasks");
    await clickButton("下一页");
    await clickButton("刷新数据");
    expect(container.textContent).toContain("第 2 / 3 页");
    expect(container.textContent).toContain("99");
    await clickButton("Accounts");
    await clickButton("Tasks");
    expect(pagedTasks()).toHaveBeenCalledTimes(3);
  });

  it("consumes a failed Tasks page action, keeps the snapshot, and emits one error toast", async () => {
    pagedTasks()
      .mockResolvedValueOnce({ items: [task(205)], page: 1, page_size: 100, total: 205, snapshot_max_id: 205 })
      .mockRejectedValueOnce(new Error("page unavailable"));
    await renderPage();
    await clickButton("Tasks");
    await clickButton("下一页");
    expect(container.textContent).toContain("第 1 / 3 页");
    expect(container.textContent).toContain("205");
    expect(pagedTasks()).toHaveBeenNthCalledWith(2, 2, 100, 205);
    expect(pushToast.mock.calls.filter(([toast]) => toast.title === "加载任务失败")).toHaveLength(1);
  });

  it("invalidates a pending Tasks request after manual fetch and ignores its late failure", async () => {
    const staleTasks = deferred<{ items: SyncTaskRead[]; page: number; page_size: number; total: number; snapshot_max_id: number }>();
    pagedTasks()
      .mockReturnValueOnce(staleTasks.promise)
      .mockResolvedValueOnce({ items: [task(301)], page: 1, page_size: 100, total: 1, snapshot_max_id: 301 });
    vi.spyOn(api, "triggerManualFetch").mockResolvedValue({
      ok: true, status: "accepted", run_id: 1, request_id: "request-1", message: "accepted",
      hourly_sync_task_id: 1, hourly_sync_task_status: "pending", hourly_sync_task_created: true,
    });

    await renderPage();
    await clickButton("Tasks");
    await clickButton("Fetch");
    const selects = container.querySelectorAll("select");
    await act(async () => {
      for (const select of selects) {
        const option = select.querySelector('option[value="1"]');
        if (option) {
          select.value = "1";
          select.dispatchEvent(new Event("change", { bubbles: true }));
        }
      }
    });
    await clickButton("Run Fetch Now");
    expect(api.listFetchSchedules).toHaveBeenCalledTimes(1);
    await clickButton("Tasks");
    expect(pagedTasks()).toHaveBeenCalledTimes(2);
    expect(container.textContent).toContain("301");

    await act(async () => staleTasks.reject(new Error("stale failure")));
    expect(container.textContent).toContain("301");
    expect(pushToast).not.toHaveBeenCalledWith(expect.objectContaining({ title: "加载任务失败" }));
  });

  it("keeps the loaded Tasks snapshot after saving a schedule", async () => {
    pagedTasks().mockResolvedValueOnce({
      items: [task(205)], page: 1, page_size: 100, total: 1, snapshot_max_id: 205,
    });
    vi.spyOn(api, "createFetchSchedule").mockResolvedValue({
      id: 1, account_id: 1, collector_instance_id: 1, enabled: true, mode: "daily_times",
      daily_times: ["08:00"], interval_hours: null, timezone: "Asia/Shanghai",
      last_triggered_at: null, next_run_at: null, last_trigger_status: null, last_trigger_message: null,
      created_at: "2026-08-18T00:00:00Z", updated_at: "2026-08-18T00:00:00Z",
    });
    await renderPage();
    await clickButton("Tasks");
    await clickButton("Fetch");
    const scheduleForm = container.querySelector("form");
    const selects = scheduleForm?.querySelectorAll("select") ?? [];
    await choose(selects[0] as HTMLSelectElement, "1");
    await choose(selects[1] as HTMLSelectElement, "1");
    await clickButton("Create Schedule");
    expect(api.listFetchSchedules).toHaveBeenCalledTimes(2);
    await clickButton("Tasks");

    expect(pagedTasks()).toHaveBeenCalledTimes(1);
  });

  it("creates a Task and immediately establishes a fresh first-page snapshot", async () => {
    pagedTasks()
      .mockResolvedValueOnce({ items: [task(205)], page: 1, page_size: 100, total: 1, snapshot_max_id: 205 })
      .mockResolvedValueOnce({ items: [task(206)], page: 1, page_size: 100, total: 2, snapshot_max_id: 206 });
    vi.spyOn(api, "createTask").mockResolvedValue({});
    await renderPage();
    await clickButton("Tasks");
    const selects = container.querySelectorAll("select");
    await choose(selects[0], "1");
    await choose(selects[1], "1");
    await clickButton("Create Task");

    expect(pagedTasks()).toHaveBeenNthCalledWith(2, 1, 100, undefined);
    expect(container.textContent).toContain("206");
  });

  it("does not report a successful Task creation as failed when the follow-up refresh fails", async () => {
    pagedTasks()
      .mockResolvedValueOnce({ items: [task(205)], page: 1, page_size: 100, total: 1, snapshot_max_id: 205 })
      .mockRejectedValueOnce(new Error("refresh unavailable"));
    vi.spyOn(api, "createTask").mockResolvedValue({});
    await renderPage();
    await clickButton("Tasks");
    const selects = container.querySelectorAll("select");
    await choose(selects[0], "1");
    await choose(selects[1], "1");
    await clickButton("Create Task");

    expect(pushToast).toHaveBeenCalledWith(expect.objectContaining({ title: "同步任务已创建", tone: "success" }));
    expect(pushToast).not.toHaveBeenCalledWith(expect.objectContaining({ title: "创建任务失败" }));
    expect(pushToast).toHaveBeenCalledWith(expect.objectContaining({ title: "加载任务失败", tone: "error" }));
  });
});
