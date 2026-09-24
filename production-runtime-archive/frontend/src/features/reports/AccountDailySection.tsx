import { SectionCard } from "../../components/ui/SectionCard";
import { formatMoney, formatNumber } from "../../lib/format";
import type { MidPlatformAccountDailyRow } from "../../types/api";

export function AccountDailySection({ rows }: { rows: MidPlatformAccountDailyRow[] }) {
  return (
    <SectionCard title="Account Daily" description="按账号聚合后的日报结果，适合直接作为中台报告入口。">
      <div className="table-card">
        <table className="data-table">
          <thead>
            <tr>
              <th>账号</th>
              <th>节点</th>
              <th>站点数</th>
              <th>Responses</th>
              <th>Impressions</th>
              <th>Clicks</th>
              <th>Revenue</th>
              <th>eCPM</th>
              <th>Run ID</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${row.instance_id}-${row.source_run_id}`}>
                <td>{row.account_name}</td>
                <td>
                  <div>{row.instance_name}</div>
                  <small className="table-meta">{row.node_account_key}</small>
                </td>
                <td>{formatNumber(row.site_count)}</td>
                <td>{formatNumber(row.responses_served)}</td>
                <td>{formatNumber(row.impressions)}</td>
                <td>{formatNumber(row.clicks)}</td>
                <td>{formatMoney(row.revenue)}</td>
                <td>{formatMoney(row.ecpm)}</td>
                <td>{row.source_run_id}</td>
              </tr>
            ))}
            {rows.length === 0 ? (
              <tr>
                <td colSpan={9} className="empty-cell">
                  暂无账号汇总结果。请先确认至少一个执行节点已经生成最新成功快照。
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </SectionCard>
  );
}
