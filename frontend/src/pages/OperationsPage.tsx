import { useCallback, useEffect, useState } from "react";

import { api, type ApiError } from "../lib/api";
import { getErrorMessage } from "../lib/errorMessages";
import { AccountsSection } from "../features/accounts/AccountsSection";
import { OAuthAppsSection } from "../features/oauth/OAuthAppsSection";
import { InstancesSection } from "../features/instances/InstancesSection";
import { ProxiesSection } from "../features/proxies/ProxiesSection";
import { TasksSection } from "../features/tasks/TasksSection";
import { useToast } from "../components/ui/useToast";
import type { AccountRead, InstanceRead, OAuthAppRead, ProxyBindingRead, SyncTaskRead } from "../types/api";

export function OperationsPage() {
  const { pushToast } = useToast();
  const [accounts, setAccounts] = useState<AccountRead[]>([]);
  const [oauthApps, setOauthApps] = useState<OAuthAppRead[]>([]);
  const [instances, setInstances] = useState<InstanceRead[]>([]);
  const [proxies, setProxies] = useState<ProxyBindingRead[]>([]);
  const [tasks, setTasks] = useState<SyncTaskRead[]>([]);
  const [loading, setLoading] = useState(true);

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const [accountsResult, oauthAppsResult, instancesResult, proxiesResult, tasksResult] = await Promise.all([
        api.listAccounts(),
        api.listOAuthApps(),
        api.listInstances(),
        api.listProxies(),
        api.listTasks(),
      ]);
      setAccounts(accountsResult.items);
      setOauthApps(oauthAppsResult.items);
      setInstances(instancesResult.items);
      setProxies(proxiesResult.items);
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
          <p>在这里完成账号接入、OAuth 配置、节点登记、代理绑定和手动任务下发，先把执行节点基础信息收干净，再交给中台聚合读取。</p>
        </div>
        <button type="button" className="secondary-button" onClick={() => void loadAll()} disabled={loading}>
          {loading ? "刷新中..." : "刷新数据"}
        </button>
      </header>

      <AccountsSection accounts={accounts} onChanged={loadAll} />
      <OAuthAppsSection accounts={accounts} oauthApps={oauthApps} onChanged={loadAll} />
      <InstancesSection accounts={accounts} instances={instances} onChanged={loadAll} />
      <ProxiesSection accounts={accounts} instances={instances} proxies={proxies} onChanged={loadAll} />
      <TasksSection accounts={accounts} instances={instances} tasks={tasks} onChanged={loadAll} />
    </div>
  );
}
