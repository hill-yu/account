import { SectionCard } from "../../components/ui/SectionCard";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { formatNullable, formatNumber } from "../../lib/format";
import type { MidPlatformNodeResult } from "../../types/api";

export function NodeResultsSection({ rows }: { rows: MidPlatformNodeResult[] }) {
  return (
    <SectionCard title="Node Results" description="每个执行节点的读取状态，方便快速判断谁没有快照、谁读取失败。">
      <div className="table-card">
        <table className="data-table">
          <thead>
            <tr>
              <th>账号</th>
              <th>节点</th>
              <th>状态</th>
              <th>HTTP</th>
              <th>Run ID</th>
              <th>Rows</th>
              <th>说明</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${row.instance_id}-${row.node_account_key}`}>
                <td>{row.account_name}</td>
                <td>
                  <div>{row.instance_name}</div>
                  <small className="table-meta">{row.node_base_url}</small>
                </td>
                <td>
                  <StatusBadge value={row.source_state} />
                </td>
                <td>{formatNullable(row.source_http_status)}</td>
                <td>{formatNullable(row.source_run_id)}</td>
                <td>{formatNumber(row.row_count)}</td>
                <td>{formatNullable(row.message)}</td>
              </tr>
            ))}
            {rows.length === 0 ? (
              <tr>
                <td colSpan={7} className="empty-cell">
                  当前还没有配置任何可读取的执行节点。
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </SectionCard>
  );
}
