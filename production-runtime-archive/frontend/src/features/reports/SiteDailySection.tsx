import { SectionCard } from "../../components/ui/SectionCard";
import { formatMoney, formatNumber } from "../../lib/format";
import type { MidPlatformSiteDailyRow } from "../../types/api";

export function SiteDailySection({ rows }: { rows: MidPlatformSiteDailyRow[] }) {
  return (
    <SectionCard title="Site Daily" description="中台聚合后的站点级结果，按节点和站点一起查看。">
      <div className="table-card">
        <table className="data-table">
          <thead>
            <tr>
              <th>账号</th>
              <th>节点</th>
              <th>站点</th>
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
              <tr key={`${row.instance_id}-${row.site_name}-${row.source_run_id}`}>
                <td>{row.account_name}</td>
                <td>
                  <div>{row.instance_name}</div>
                  <small className="table-meta">{row.node_account_key}</small>
                </td>
                <td>{row.site_name}</td>
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
                  暂无可展示的站点结果。请先确认至少一个执行节点已经生成最新成功快照。
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </SectionCard>
  );
}
