import { SectionCard } from "../../components/ui/SectionCard";
import { formatMoney, formatNumber } from "../../lib/format";
import type { MidPlatformSummary } from "../../types/api";

export function SummarySection({
  summary,
  timezone,
}: {
  summary: MidPlatformSummary | null;
  timezone: string;
}) {
  const cards = summary
    ? [
        { label: "Timezone", value: timezone, compact: true },
        { label: "Requested Nodes", value: formatNumber(summary.requested_node_count) },
        { label: "Success Nodes", value: formatNumber(summary.success_node_count) },
        { label: "No Snapshot Nodes", value: formatNumber(summary.no_snapshot_node_count) },
        { label: "Error Nodes", value: formatNumber(summary.error_node_count) },
        { label: "Responses", value: formatNumber(summary.total_responses_served) },
        { label: "Impressions", value: formatNumber(summary.total_impressions) },
        { label: "Clicks", value: formatNumber(summary.total_clicks) },
        { label: "Revenue", value: formatMoney(summary.total_revenue) },
      ]
    : [];

  return (
    <SectionCard title="Summary" description="Review the aggregated totals first, then inspect the node and site details.">
      {summary ? (
        <div className="summary-grid">
          {cards.map((card) => (
            <article key={card.label} className={`summary-card${card.compact ? " summary-card-compact" : ""}`}>
              <span className="summary-label">{card.label}</span>
              <strong className="summary-value">{card.value}</strong>
            </article>
          ))}
        </div>
      ) : (
        <div className="empty-note">Load one report date first, and the aggregated summary will appear here.</div>
      )}
    </SectionCard>
  );
}
