import { useEffect, useState } from "react";

import { api, type ApiError } from "../lib/api";
import { getErrorMessage } from "../lib/errorMessages";
import { SiteDailySection } from "../features/reports/SiteDailySection";
import { AccountDailySection } from "../features/reports/AccountDailySection";
import { NodeResultsSection } from "../features/reports/NodeResultsSection";
import { SummarySection } from "../features/reports/SummarySection";
import type {
  AccountRead,
  MidPlatformAccountDailyRow,
  MidPlatformNodeResult,
  MidPlatformSiteDailyRow,
  MidPlatformSummary,
} from "../types/api";
import { useToast } from "../components/ui/useToast";

const REPORT_TABS = [
  { key: "nodes", label: "Node Results" },
  { key: "account", label: "Account Daily" },
  { key: "site", label: "Site Daily" },
] as const;

type ReportTab = (typeof REPORT_TABS)[number]["key"];

export function ReportsPage() {
  const { pushToast } = useToast();
  const [accounts, setAccounts] = useState<AccountRead[]>([]);
  const [siteRows, setSiteRows] = useState<MidPlatformSiteDailyRow[]>([]);
  const [accountRows, setAccountRows] = useState<MidPlatformAccountDailyRow[]>([]);
  const [nodeResults, setNodeResults] = useState<MidPlatformNodeResult[]>([]);
  const [summary, setSummary] = useState<MidPlatformSummary | null>(null);
  const [reportTimezone, setReportTimezone] = useState("America/Los_Angeles");
  const [accountId, setAccountId] = useState("");
  const [reportDate, setReportDate] = useState(new Date().toISOString().slice(0, 10));
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<ReportTab>("nodes");

  useEffect(() => {
    void api
      .listAccounts()
      .then((result) => setAccounts(result.items))
      .catch((error) => {
        pushToast({
          title: "加载账号列表失败",
          message: getErrorMessage(error as ApiError),
          tone: "error",
        });
      });
  }, [pushToast]);

  const handleLoad = async () => {
    setLoading(true);
    try {
      const numericAccountId = accountId ? Number(accountId) : undefined;
      const [siteResult, accountResult] = await Promise.all([
        api.listMidPlatformSiteDailyReports(numericAccountId, reportDate || undefined),
        api.listMidPlatformAccountDailyReports(numericAccountId, reportDate || undefined),
      ]);

      setSiteRows(siteResult.items);
      setAccountRows(accountResult.items);
      setNodeResults(siteResult.node_results);
      setSummary(siteResult.summary);
      setReportTimezone(siteResult.timezone || accountResult.timezone || "America/Los_Angeles");

      pushToast({
        title: "报告已刷新",
        message: "中台聚合结果已经加载完成。",
        tone: "success",
      });
    } catch (error) {
      pushToast({
        title: "加载报告失败",
        message: getErrorMessage(error as ApiError),
        tone: "error",
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="page-stack">
      <header className="page-header">
        <div>
          <p className="page-kicker">Reports</p>
          <h2>中台聚合报告</h2>
          <p>按日期统一读取各执行节点的最新成功快照。</p>
        </div>
      </header>

      <section className="filters-panel">
        <label className="field">
          <span className="field-label">账号</span>
          <select className="field-control" value={accountId} onChange={(event) => setAccountId(event.target.value)}>
            <option value="">全部账号</option>
            {accounts.map((account) => (
              <option key={account.id} value={account.id}>
                {account.id} - {account.name}
              </option>
            ))}
          </select>
        </label>

        <label className="field">
          <span className="field-label">日期</span>
          <input className="field-control" type="date" value={reportDate} onChange={(event) => setReportDate(event.target.value)} />
        </label>

        <div className="filters-actions">
          <button type="button" className="primary-button" onClick={handleLoad} disabled={loading}>
            {loading ? "加载中..." : "加载报告"}
          </button>
        </div>
      </section>

      <section className="report-timezone-note">
        <strong>Report Date Timezone</strong>
        <span>{reportTimezone}</span>
      </section>

      <SummarySection summary={summary} timezone={reportTimezone} />

      <div className="tab-bar">
        {REPORT_TABS.map((tab) => (
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

      {activeTab === "nodes" && <NodeResultsSection rows={nodeResults} />}
      {activeTab === "account" && <AccountDailySection rows={accountRows} />}
      {activeTab === "site" && <SiteDailySection rows={siteRows} />}
    </div>
  );
}
