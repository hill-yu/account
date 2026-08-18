import { useCallback, useRef, useState } from "react";

import { useToast } from "../../components/ui/useToast";
import { api, type ApiError } from "../../lib/api";
import { getErrorMessage } from "../../lib/errorMessages";
import type { AccountRead, FetchScheduleRead, InstanceRead, OAuthAppRead, ProxyBindingRead, SyncTaskRead } from "../../types/api";

export type OperationsTab = "accounts" | "oauth" | "instances" | "proxies" | "fetch" | "tasks";

type ResourceState<T> = { data: T; loaded: boolean; loading: boolean; error: string | null };
type ResourceControl = { requestId: number; pending: Promise<void> | null };

function useResource<T>(initial: T, fetcher: () => Promise<T>, errorTitle: string) {
  const { pushToast } = useToast();
  const [state, setState] = useState<ResourceState<T>>({ data: initial, loaded: false, loading: false, error: null });
  const stateRef = useRef(state);
  stateRef.current = state;
  const control = useRef<ResourceControl>({ requestId: 0, pending: null });

  const load = useCallback((force = false): Promise<void> => {
    if (!force && stateRef.current.loaded) return Promise.resolve();
    if (!force && control.current.pending) return control.current.pending;
    const requestId = ++control.current.requestId;
    const wasLoaded = stateRef.current.loaded;
    setState((current) => ({ ...current, loading: true, error: null }));
    let pending: Promise<void>;
    pending = fetcher().then(
      (data) => {
        if (control.current.requestId === requestId && control.current.pending === pending) {
          setState({ data, loaded: true, loading: false, error: null });
        }
      },
      (error: unknown) => {
        if (control.current.requestId === requestId && control.current.pending === pending) {
          const message = getErrorMessage(error as ApiError);
          setState((current) => ({ ...current, loaded: wasLoaded, loading: false, error: message }));
          pushToast({ title: errorTitle, message, tone: "error" });
        }
        throw error;
      },
    ).finally(() => {
      if (control.current.requestId === requestId && control.current.pending === pending) control.current.pending = null;
    });
    control.current.pending = pending;
    return pending;
  }, [errorTitle, fetcher, pushToast]);

  return { ...state, load };
}

const fetchAccounts = () => api.listAccounts().then((result) => result.items);
const fetchOAuthApps = () => api.listOAuthApps().then((result) => result.items);
const fetchInstances = () => api.listInstances().then((result) => result.items);
const fetchProxies = () => api.listProxies().then((result) => result.items);
const fetchSchedules = () => api.listFetchSchedules().then((result) => result.items);

export function useOperationsData() {
  const { pushToast } = useToast();
  const accounts = useResource<AccountRead[]>([], fetchAccounts, "加载账户失败");
  const oauthApps = useResource<OAuthAppRead[]>([], fetchOAuthApps, "加载 OAuth Apps 失败");
  const instances = useResource<InstanceRead[]>([], fetchInstances, "加载实例失败");
  const proxies = useResource<ProxyBindingRead[]>([], fetchProxies, "加载代理失败");
  const schedules = useResource<FetchScheduleRead[]>([], fetchSchedules, "加载调度失败");
  const [tasks, setTasks] = useState({ items: [] as SyncTaskRead[], page: 1, pageSize: 100, total: 0, snapshot: 0, loaded: false, loading: false, error: null as string | null });
  const tasksRef = useRef(tasks);
  tasksRef.current = tasks;
  const tasksControl = useRef<ResourceControl>({ requestId: 0, pending: null });

  const loadTasks = useCallback((page = 1, force = false): Promise<void> => {
    if (!force && tasksRef.current.loaded && page === tasksRef.current.page) return Promise.resolve();
    if (!force && tasksControl.current.pending) return tasksControl.current.pending;
    const requestId = ++tasksControl.current.requestId;
    const wasLoaded = tasksRef.current.loaded;
    const snapshot = page === 1 ? undefined : tasksRef.current.snapshot || undefined;
    setTasks((current) => ({ ...current, loading: true, error: null }));
    let pending: Promise<void>;
    pending = api.listTasksPaged(page, tasksRef.current.pageSize, snapshot).then(
      (result) => {
        if (tasksControl.current.requestId === requestId && tasksControl.current.pending === pending) {
          setTasks({ items: result.items, page: result.page, pageSize: result.page_size, total: result.total, snapshot: result.snapshot_max_id, loaded: true, loading: false, error: null });
        }
      },
      (error: unknown) => {
        if (tasksControl.current.requestId === requestId && tasksControl.current.pending === pending) {
          const message = getErrorMessage(error as ApiError);
          setTasks((current) => ({ ...current, loaded: wasLoaded, loading: false, error: message }));
          pushToast({ title: "加载任务失败", message, tone: "error" });
        }
        throw error;
      },
    ).finally(() => {
      if (tasksControl.current.requestId === requestId && tasksControl.current.pending === pending) tasksControl.current.pending = null;
    });
    tasksControl.current.pending = pending;
    return pending;
  }, [pushToast]);

  const invalidateTasks = useCallback(() => {
    ++tasksControl.current.requestId;
    tasksControl.current.pending = null;
    setTasks({ items: [], page: 1, pageSize: 100, total: 0, snapshot: 0, loaded: false, loading: false, error: null });
  }, []);

  const dependencies: Record<Exclude<OperationsTab, "tasks">, Array<(force?: boolean) => Promise<void>>> = {
    accounts: [accounts.load],
    oauth: [accounts.load, oauthApps.load],
    instances: [accounts.load, instances.load],
    proxies: [accounts.load, instances.load, proxies.load],
    fetch: [accounts.load, instances.load, schedules.load],
  };
  const loadTab = useCallback((tab: OperationsTab, force = false) => {
    const requests = tab === "tasks"
      ? [accounts.load(force), instances.load(force), !force && tasksRef.current.loaded ? Promise.resolve() : loadTasks(1, force)]
      : dependencies[tab].map((load) => load(force));
    return Promise.allSettled(requests).then(() => undefined);
  // Resource load callbacks are stable because their fetchers are module-level functions.
  }, [accounts.load, instances.load, oauthApps.load, proxies.load, schedules.load, loadTasks]);

  return { accounts, oauthApps, instances, proxies, schedules, tasks, loadTab, loadTasks, invalidateTasks };
}
