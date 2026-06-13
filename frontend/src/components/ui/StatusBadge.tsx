export function StatusBadge({ value }: { value: string }) {
  const tone = getStatusTone(value);
  return <span className={`status-badge status-${tone}`}>{value}</span>;
}

function getStatusTone(value: string): string {
  switch (value) {
    case "active":
    case "ready":
    case "authorized":
    case "succeeded":
    case "verified":
      return "success";
    case "failed":
    case "error":
    case "disabled":
    case "revoked":
    case "rejected":
      return "danger";
    case "blocked":
    case "expired":
    case "no_snapshot":
      return "warning";
    case "pending":
    case "provisioning":
    case "in_progress":
      return "info";
    default:
      return "neutral";
  }
}
