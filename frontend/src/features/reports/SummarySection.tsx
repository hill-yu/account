import { SectionCard } from "../../components/ui/SectionCard";
import { formatMoney, formatNumber } from "../../lib/format";
import type { MidPlatformSummary } from "../../types/api";

export function SummarySection({ summary }: { summary: MidPlatformSummary | null }) {
  const cards = summary
    ? [
        { label: "请求节点", value: formatNumber(summary.requested_node_count) },
        { label: "成功节点", value: formatNumber(summary.success_node_count) },
        { label: "无快照节点", value: formatNumber(summary.no_snapshot_node_count) },
        { label: "异常节点", value: formatNumber(summary.error_node_count) },
        { label: "Responses", value: formatNumber(summary.total_responses_served) },
        { label: "Impressions", value: formatNumber(summary.total_impressions) },
        { label: "Clicks", value: formatNumber(summary.total_clicks) },
        { label: "Revenue", value: formatMoney(summary.total_revenue) },
      ]
    : [];

  return (
    <SectionCard title="Summary" description="中台聚合后的总览，先看节点状态，再看整体量级。">
      {summary ? (
        <div className="summary-grid">
          {cards.map((card) => (
            <article key={card.label} className="summary-card">
              <span className="summary-label">{card.label}</span>
              <strong className="summary-value">{card.value}</strong>
            </article>
          ))}
        </div>
      ) : (
        <div className="empty-note">先选择日期并点击“加载报告”，这里会显示中台聚合后的总览。</div>
      )}
    </SectionCard>
  );
}
