import { useCallback, useEffect, useState } from "react";

import { AccountsSection } from "../features/accounts/AccountsSection";
import { FetchSchedulesSection } from "../features/fetch/FetchSchedulesSection";
import { InstancesSection } from "../features/instances/InstancesSection";
import { OAuthAppsSection } from "../features/oauth/OAuthAppsSection";
import { ProxiesSection } from "../features/proxies/ProxiesSection";
import { TasksSection } from "../features/tasks/TasksSection";
import { useOperationsData, type OperationsTab } from "../features/operations/useOperationsData";

const TABS = [
  { key: "accounts", label: "Accounts" }, { key: "oauth", label: "OAuth Apps" },
  { key: "instances", label: "Instances" }, { key: "proxies", label: "Proxies" },
  { key: "fetch", label: "Fetch" }, { key: "tasks", label: "Tasks" },
] as const;

export function OperationsPage() {
  const [activeTab, setActiveTab] = useState<OperationsTab>("accounts");
  const data = useOperationsData();
  useEffect(() => { void data.loadTab(activeTab); }, [activeTab, data.loadTab]);
  const refreshActiveTab = useCallback(() => data.loadTab(activeTab, true), [activeTab, data.loadTab]);
  const activeLoading = activeTab === "tasks" ? data.accounts.loading || data.instances.loading || data.tasks.loading
    : activeTab === "accounts" ? data.accounts.loading
    : activeTab === "oauth" ? data.accounts.loading || data.oauthApps.loading
    : activeTab === "instances" ? data.accounts.loading || data.instances.loading
    : activeTab === "proxies" ? data.accounts.loading || data.instances.loading || data.proxies.loading
    : data.accounts.loading || data.instances.loading || data.schedules.loading;
  const refreshTasksAfterCreate = useCallback(async () => {
    data.invalidateTasks();
    await data.loadTasks(1, true);
  }, [data.invalidateTasks, data.loadTasks]);

  return <div className="page-stack">
    <header className="page-header"><div><p className="page-kicker">Operations</p><h2>接入与执行</h2><p>管理账号接入、OAuth 配置、节点登记、代理绑定和手动任务下发。</p></div>
      <button type="button" className="secondary-button" onClick={() => void refreshActiveTab()} disabled={activeLoading}>{activeLoading ? "刷新中..." : "刷新数据"}</button>
    </header>
    <div className="tab-bar">{TABS.map((tab) => <button key={tab.key} type="button" className={`tab-item${activeTab === tab.key ? " active" : ""}`} onClick={() => setActiveTab(tab.key)}>{tab.label}</button>)}</div>
    {activeTab === "accounts" && <AccountsSection accounts={data.accounts.data} onChanged={() => data.accounts.load(true)} />}
    {activeTab === "oauth" && <OAuthAppsSection accounts={data.accounts.data} oauthApps={data.oauthApps.data} onChanged={() => data.oauthApps.load(true)} />}
    {activeTab === "instances" && <InstancesSection accounts={data.accounts.data} instances={data.instances.data} onChanged={() => data.instances.load(true)} />}
    {activeTab === "proxies" && <ProxiesSection accounts={data.accounts.data} instances={data.instances.data} proxies={data.proxies.data} onChanged={() => data.proxies.load(true)} />}
    {activeTab === "fetch" && <FetchSchedulesSection accounts={data.accounts.data} instances={data.instances.data} schedules={data.schedules.data} onScheduleChanged={() => data.schedules.load(true)} onManualFetchChanged={data.invalidateTasks} />}
    {activeTab === "tasks" && <TasksSection accounts={data.accounts.data} instances={data.instances.data} tasks={data.tasks.items} onChanged={refreshTasksAfterCreate} page={data.tasks.page} pageSize={data.tasks.pageSize} total={data.tasks.total} loading={data.tasks.loading} onPreviousPage={() => { void data.loadTasks(data.tasks.page - 1).catch(() => undefined); }} onNextPage={() => { void data.loadTasks(data.tasks.page + 1).catch(() => undefined); }} />}
  </div>;
}
