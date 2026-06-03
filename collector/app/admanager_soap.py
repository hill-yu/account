from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

REQUIRED_CSV_COLUMNS = (
    "Dimension.DATE_PT",
    "Dimension.SITE_NAME",
    "Column.AD_EXCHANGE_RESPONSES_SERVED",
    "Column.AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS",
    "Column.AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS",
    "Column.AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE",
    "Column.AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM",
)


def _google_date(value: date) -> dict[str, int]:
    return {"year": value.year, "month": value.month, "day": value.day}


@dataclass(frozen=True)
class SoapReportDefinition:
    dimensions: tuple[str, ...] = ("DATE_PT", "SITE_NAME")
    columns: tuple[str, ...] = (
        "AD_EXCHANGE_RESPONSES_SERVED",
        "AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS",
        "AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS",
        "AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE",
        "AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM",
    )
    time_zone_type: str = "PACIFIC"
    schema_version: str = "admanager_site_core_v1"

    def build_report_query(self, *, task_id: int, report_date: date) -> dict[str, object]:
        return {
            "dimensions": list(self.dimensions),
            "columns": list(self.columns),
            "dateRangeType": "CUSTOM_DATE",
            "startDate": _google_date(report_date),
            "endDate": _google_date(report_date),
            "timeZoneType": self.time_zone_type,
        }


def parse_report_csv(raw_csv: str, *, report_date: date) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    reader = csv.DictReader(io.StringIO(raw_csv))
    _validate_required_columns(reader.fieldnames)
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
                "url_id": _require_text(row, "Dimension.SITE_NAME"),
                "url": _require_text(row, "Dimension.SITE_NAME"),
                "responses_served": _parse_int(
                    row.get("Column.AD_EXCHANGE_RESPONSES_SERVED"),
                    field_name="Column.AD_EXCHANGE_RESPONSES_SERVED",
                ),
                "impressions": _parse_int(
                    row.get("Column.AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS"),
                    field_name="Column.AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS",
                ),
                "clicks": _parse_int(
                    row.get("Column.AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS"),
                    field_name="Column.AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS",
                ),
                "revenue": _parse_micros_decimal_string(
                    row.get("Column.AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE"),
                    field_name="Column.AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE",
                ),
                "ecpm": _parse_micros_decimal_string(
                    row.get("Column.AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM"),
                    field_name="Column.AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM",
                ),
            }
        )
    return rows


def _validate_required_columns(fieldnames: list[str] | None) -> None:
    seen = set(fieldnames or [])
    missing = [column_name for column_name in REQUIRED_CSV_COLUMNS if column_name not in seen]
    if missing:
        raise ValueError(f"Ad Manager report CSV is missing required columns: {', '.join(missing)}")


def _require_text(row: dict[str, str | None], field_name: str) -> str:
    text = (row.get(field_name) or "").strip()
    if text == "":
        raise ValueError(f"Missing required text cell value: {field_name}")
    return text


def _parse_int(value: str | None, *, field_name: str) -> int:
    text = (value or "").replace(",", "").strip()
    if text == "":
        raise ValueError(f"Missing required integer cell value: {field_name}")
    try:
        decimal_value = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid integer cell value: {value}") from exc
    if not decimal_value.is_finite():
        raise ValueError(f"Invalid integer cell value: {value}")
    if decimal_value != decimal_value.to_integral_value():
        raise ValueError(f"Invalid integer cell value: {value}")
    return int(decimal_value)


def _parse_decimal_string(value: str | None, *, field_name: str) -> str:
    text = (value or "").replace(",", "").strip()
    if text == "":
        raise ValueError(f"Missing required decimal cell value: {field_name}")
    try:
        decimal_value = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid decimal cell value: {value}") from exc
    if not decimal_value.is_finite():
        raise ValueError(f"Invalid decimal cell value: {value}")
    return format(decimal_value.quantize(Decimal("0.000001")), "f")


def _parse_micros_decimal_string(value: str | None, *, field_name: str) -> str:
    decimal_string = _parse_decimal_string(value, field_name=field_name)
    decimal_value = Decimal(decimal_string) / Decimal("1000000")
    return format(decimal_value.quantize(Decimal("0.000001")), "f")


class AdManagerSoapClient:
    def __init__(
        self,
        *,
        network_code: str,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        application_name: str = "adx-account-isolated-collector",
        api_version: str = "v202602",
        timeout_seconds: int = 30,
        downloader_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._network_code = network_code
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._application_name = application_name
        self._api_version = api_version
        self._timeout_seconds = timeout_seconds
        self._report_definition = SoapReportDefinition()
        self._downloader_factory = downloader_factory

    @property
    def report_definition(self) -> SoapReportDefinition:
        return self._report_definition

    def fetch_rows(self, *, task_id: int, report_date: date) -> list[dict[str, object]]:
        downloader = self._build_downloader()
        report_job_id = downloader.WaitForReport(
            {
                "reportQuery": self._report_definition.build_report_query(
                    task_id=task_id,
                    report_date=report_date,
                )
            },
            poll_time_seconds=2,
        )
        csv_io = io.BytesIO()
        downloader.DownloadReportToFile(
            report_job_id,
            export_format="CSV_DUMP",
            outfile=csv_io,
            include_report_properties=False,
            include_totals_row=False,
            use_gzip_compression=False,
        )
        return parse_report_csv(
            csv_io.getvalue().decode("utf-8", errors="ignore"),
            report_date=report_date,
        )

    def _build_downloader(self) -> Any:
        if self._downloader_factory is not None:
            return self._downloader_factory()

        try:
            from googleads import ad_manager, oauth2
        except ImportError as exc:
            raise RuntimeError("googleads dependency is required for admanager_soap fetch mode") from exc

        oauth2_client = oauth2.GoogleRefreshTokenClient(
            self._client_id,
            self._client_secret,
            self._refresh_token,
        )
        client = ad_manager.AdManagerClient(
            oauth2_client,
            self._application_name,
            network_code=self._network_code,
            cache=None,
            timeout=self._timeout_seconds,
        )
        return client.GetDataDownloader(version=self._api_version)
