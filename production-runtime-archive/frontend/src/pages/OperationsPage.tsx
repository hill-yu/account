import { useCallback, useEffect, useState } from "react";

import { api, type ApiError } from "../lib/api";
import { getErrorMessage } from "../lib/errorMessages";
import { AccountsSection } from "../features/accounts/AccountsSection";
import { OAuthAppsSection } from "../features/oauth/OAuthAppsSection";
import { InstancesSection } from "../features/instances/InstancesSection";
import { ProxiesSection } from "../features/proxies/ProxiesSection";
import { TasksSection } from "../features/tasks/TasksSection";
import { FetchSchedulesSection } from "../features/fetch/FetchSchedulesSection";
import { useToast } from "../components/ui/useToast";
import type { AccountRead, FetchScheduleRead, InstanceRead, OAuthAppRead, ProxyBindingRead, SyncTaskRead } from "../types/api";

const TABS = [
  { key: "accounts", label: "Accounts" },
  { key: "oauth", label: "OAuth Apps" },
  { key: "instances", label: "Instances" },
  { key: "proxies", label: "Proxies" },
  { key: "fetch", label: "Fetch" },
  { key: "tasks", label: "Tasks" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

export function OperationsPage() {
  const { pushToast } = useToast();
  const [activeTab, setActiveTab] = useState<TabKey>("accounts");
  const [accounts, setAccounts] = useState<AccountRead[]>([]);
  const [oauthApps, setOauthApps] = useState<OAuthAppRead[]>([]);
  const [instances, setInstances] = useState<InstanceRead[]>([]);
  const [proxies, setProxies] = useState<ProxyBindingRead[]>([]);
  const [fetchSchedules, setFetchSchedules] = useState<FetchScheduleRead[]>([]);
  const [tasks, setTasks] = useState<SyncTaskRead[]>([]);
  const [loading, setLoading] = useState(true);

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const [accountsResult, oauthAppsResult, instancesResult, proxiesResult, fetchSchedulesResult, tasksResult] = await Promise.all([
        api.listAccounts(),
        api.listOAuthApps(),
        api.listInstances(),
        api.listProxies(),
        api.listFetchSchedules(),
        api.listTasks(),
      ]);
      setAccounts(accountsResult.items);
      setOauthApps(oauthAppsResult.items);
      setInstances(instancesResult.items);
      setProxies(proxiesResult.items);
      setFetchSchedules(fetchSchedulesResult.items);
      setTasks(tasksResult.items);
    } catch (error) {
      const message = getErrorMessage(error as ApiError);
      pushToast({ title: "加载控制台数据失败", message, tone: "error" });
    } finally {
      setLoading(false);
    }
  }, [pushToast]);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  return (
    <div className="page-stack">
      <header className="page-header">
        <div>
          <p className="page-kicker">Operations</p>
          <h2>接入与执行</h2>
          <p>管理账号接入、OAuth 配置、节点登记、代理绑定和手动任务下发。</p>
        </div>
        <button type="button" className="secondary-button" onClick={() => void loadAll()} disabled={loading}>
          {loading ? "刷新中..." : "刷新数据"}
        </button>
      </header>

      <div className="tab-bar">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            className={`tab-item${activeTab === tab.key ? " active" : ""}`}
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === "accounts" && <AccountsSection accounts={accounts} onChanged={loadAll} />}
      {activeTab === "oauth" && <OAuthAppsSection accounts={accounts} oauthApps={oauthApps} onChanged={loadAll} />}
      {activeTab === "instances" && <InstancesSection accounts={accounts} instances={instances} onChanged={loadAll} />}
      {activeTab === "proxies" && <ProxiesSection accounts={accounts} instances={instances} proxies={proxies} onChanged={loadAll} />}
      {activeTab === "fetch" && (
        <FetchSchedulesSection
          accounts={accounts}
          instances={instances}
          schedules={fetchSchedules}
          onChanged={loadAll}
        />
      )}
      {activeTab === "tasks" && <TasksSection accounts={accounts} instances={instances} tasks={tasks} onChanged={loadAll} />}
    </div>
  );
}
