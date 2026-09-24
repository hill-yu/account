const PLACEHOLDER = "—";

export function formatNullable(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") {
    return PLACEHOLDER;
  }

  return String(value);
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return PLACEHOLDER;
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function formatNumber(value: number | null | undefined, fractionDigits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return PLACEHOLDER;
  }

  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  }).format(value);
}

export function formatMoney(value: number | null | undefined): string {
  return formatNumber(value, 2);
}

