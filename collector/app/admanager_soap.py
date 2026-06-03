from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation


def _google_date(value: date) -> dict[str, int]:
    return {"year": value.year, "month": value.month, "day": value.day}


@dataclass(frozen=True)
class SoapReportDefinition:
    dimensions: tuple[str, ...] = ("DATE_PT", "URL_ID", "URL_NAME")
    columns: tuple[str, ...] = (
        "AD_EXCHANGE_RESPONSES_SERVED",
        "AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS",
        "AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS",
        "AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE",
        "AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM",
    )
    report_type: str = "HISTORICAL"
    time_zone_type: str = "PACIFIC"
    schema_version: str = "admanager_site_core_v1"

    def build_report_query(self, *, task_id: int, report_date: date) -> dict[str, object]:
        return {
            "dimensions": list(self.dimensions),
            "columns": list(self.columns),
            "dateRangeType": "CUSTOM_DATE",
            "startDate": _google_date(report_date),
            "endDate": _google_date(report_date),
            "reportType": self.report_type,
            "timeZoneType": self.time_zone_type,
        }


def parse_report_csv(raw_csv: str, *, report_date: date) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    reader = csv.DictReader(io.StringIO(raw_csv))
    for row in reader:
        if not any((value or "").strip() for value in row.values()):
            continue
        row_date = (row.get("Dimension.DATE_PT") or "").strip()
        if row_date != report_date.isoformat():
            raise ValueError(
                "Unexpected Ad Manager report row date: "
                f"{row_date!r} (expected {report_date.isoformat()!r})"
            )
        rows.append(
            {
                "report_date": report_date.isoformat(),
                "url_id": (row.get("Dimension.URL_ID") or "").strip(),
                "url": (row.get("Dimension.URL_NAME") or "").strip(),
                "responses_served": _parse_int(row.get("Column.AD_EXCHANGE_RESPONSES_SERVED")),
                "impressions": _parse_int(row.get("Column.AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS")),
                "clicks": _parse_int(row.get("Column.AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS")),
                "revenue": _parse_decimal_string(row.get("Column.AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE")),
                "ecpm": _parse_decimal_string(row.get("Column.AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM")),
            }
        )
    return rows


def _parse_int(value: str | None) -> int:
    text = (value or "").replace(",", "").strip()
    if text == "":
        return 0
    try:
        decimal_value = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid integer cell value: {value}") from exc
    if decimal_value != decimal_value.to_integral_value():
        raise ValueError(f"Invalid integer cell value: {value}")
    return int(decimal_value)


def _parse_decimal_string(value: str | None) -> str:
    text = (value or "").replace(",", "").strip()
    if text == "":
        return "0.000000"
    try:
        return format(Decimal(text).quantize(Decimal("0.000001")), "f")
    except InvalidOperation as exc:
        raise ValueError(f"Invalid decimal cell value: {value}") from exc
