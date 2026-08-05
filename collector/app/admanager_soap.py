from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from app.proxy import ProxyConfig

REQUIRED_CSV_COLUMNS = (
    "Dimension.SITE_NAME",
    "Column.AD_EXCHANGE_RESPONSES_SERVED",
    "Column.AD_EXCHANGE_TOTAL_REQUESTS",
    "Column.AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS",
    "Column.AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS",
    "Column.AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE",
    "Column.AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM",
)

DAILY_DATE_COLUMNS = ("Dimension.DATE", "Dimension.DATE_PT")

HOURLY_REQUIRED_CSV_COLUMNS = (
    "Dimension.DATE_PT",
    "Dimension.HOUR",
    "Dimension.SITE_NAME",
    "Dimension.COUNTRY_CODE",
    "Dimension.AD_UNIT_ID",
    "Dimension.AD_UNIT_NAME",
    "Column.AD_EXCHANGE_RESPONSES_SERVED",
    "Column.AD_EXCHANGE_TOTAL_REQUESTS",
    "Column.AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS",
    "Column.AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS",
    "Column.AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE",
    "Column.AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM",
)

DAILY_DIMENSION_REQUIRED_CSV_COLUMNS = (
    "Dimension.SITE_NAME",
    "Dimension.COUNTRY_CODE",
    "Dimension.AD_UNIT_ID",
    "Dimension.AD_UNIT_NAME",
    *REQUIRED_CSV_COLUMNS[1:],
)

MISSING_SITE_NAME_PLACEHOLDER = "__missing_site_name__"


def _google_date(value: date) -> dict[str, int]:
    return {"year": value.year, "month": value.month, "day": value.day}


@dataclass(frozen=True)
class SoapReportDefinition:
    dimensions: tuple[str, ...] = ("DATE", "SITE_NAME")
    columns: tuple[str, ...] = (
        "AD_EXCHANGE_RESPONSES_SERVED",
        "AD_EXCHANGE_TOTAL_REQUESTS",
        "AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS",
        "AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS",
        "AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE",
        "AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM",
    )
    time_zone_type: str = "PUBLISHER"
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


@dataclass(frozen=True)
class HourlyDimensionSoapReportDefinition:
    dimensions: tuple[str, ...] = ("DATE_PT", "HOUR", "SITE_NAME", "COUNTRY_CODE", "AD_UNIT_ID")
    columns: tuple[str, ...] = (
        "AD_EXCHANGE_RESPONSES_SERVED",
        "AD_EXCHANGE_TOTAL_REQUESTS",
        "AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS",
        "AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS",
        "AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE",
        "AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM",
    )
    time_zone_type: str = "PACIFIC"
    source_timezone: str = "America/Los_Angeles"
    schema_version: str = "admanager_hourly_dimension_v1"

    def build_report_query(self, *, task_id: int, report_date: date) -> dict[str, object]:
        return {
            "dimensions": list(self.dimensions),
            "columns": list(self.columns),
            "dateRangeType": "CUSTOM_DATE",
            "startDate": _google_date(report_date),
            "endDate": _google_date(report_date),
            "timeZoneType": self.time_zone_type,
        }


@dataclass(frozen=True)
class DailyDimensionSoapReportDefinition:
    dimensions: tuple[str, ...] = ("DATE", "SITE_NAME", "COUNTRY_CODE", "AD_UNIT_ID")
    columns: tuple[str, ...] = SoapReportDefinition.columns
    time_zone_type: str = "PUBLISHER"
    schema_version: str = "admanager_daily_dimension_v1"

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
    date_column = _resolve_daily_date_column(reader.fieldnames)
    for row in reader:
        if not any((value or "").strip() for value in row.values()):
            continue
        row_date = (row.get(date_column) or "").strip()
        if row_date != report_date.isoformat():
            raise ValueError(
                "Unexpected Ad Manager report row date: "
                f"{row_date!r} (expected {report_date.isoformat()!r})"
            )
        rows.append(
            {
                "report_date": report_date.isoformat(),
                "url_id": _site_name_or_placeholder(row),
                "url": _site_name_or_placeholder(row),
                "responses_served": _parse_int_or_zero_when_missing(
                    row.get("Column.AD_EXCHANGE_RESPONSES_SERVED"),
                    field_name="Column.AD_EXCHANGE_RESPONSES_SERVED",
                ),
                "requests": _parse_int_or_zero_when_missing(
                    row.get("Column.AD_EXCHANGE_TOTAL_REQUESTS"),
                    field_name="Column.AD_EXCHANGE_TOTAL_REQUESTS",
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


def parse_hourly_report_csv(
    raw_csv: str,
    *,
    report_date: date,
    source_timezone: str = "America/Los_Angeles",
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    reader = csv.DictReader(io.StringIO(raw_csv))
    _validate_required_columns(reader.fieldnames, required_columns=HOURLY_REQUIRED_CSV_COLUMNS)
    for row in reader:
        if not any((value or "").strip() for value in row.values()):
            continue
        row_date = (row.get("Dimension.DATE_PT") or "").strip()
        if row_date != report_date.isoformat():
            raise ValueError(
                "Unexpected Ad Manager hourly report row date: "
                f"{row_date!r} (expected {report_date.isoformat()!r})"
            )
        rows.append(
            {
                "report_date": report_date.isoformat(),
                "hour": _parse_hour_value(row.get("Dimension.HOUR")),
                "source_timezone": source_timezone,
                "url_id": _site_name_or_placeholder(row),
                "url": _site_name_or_placeholder(row),
                "ad_country_code": (row.get("Dimension.COUNTRY_CODE") or "").strip(),
                "ad_country_name": (row.get("Dimension.COUNTRY_CODE") or "").strip(),
                "ad_slot_id": (row.get("Dimension.AD_UNIT_ID") or "").strip(),
                "ad_slot_name": ((row.get("Dimension.AD_UNIT_NAME") or row.get("Dimension.AD_UNIT_ID")) or "").strip(),
                "responses_served": _parse_int_or_zero_when_missing(
                    row.get("Column.AD_EXCHANGE_RESPONSES_SERVED"),
                    field_name="Column.AD_EXCHANGE_RESPONSES_SERVED",
                ),
                "requests": _parse_int_or_zero_when_missing(
                    row.get("Column.AD_EXCHANGE_TOTAL_REQUESTS"),
                    field_name="Column.AD_EXCHANGE_TOTAL_REQUESTS",
                ),
                "impressions": _parse_int_or_zero_when_missing(
                    row.get("Column.AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS"),
                    field_name="Column.AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS",
                ),
                "clicks": _parse_int_or_zero_when_missing(
                    row.get("Column.AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS"),
                    field_name="Column.AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS",
                ),
                "revenue": _parse_micros_or_zero_when_missing(
                    row.get("Column.AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE"),
                    field_name="Column.AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE",
                ),
                "ecpm": _parse_micros_or_zero_when_missing(
                    row.get("Column.AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM"),
                    field_name="Column.AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM",
                ),
            }
        )
    return rows


def parse_daily_dimension_report_csv(raw_csv: str, *, report_date: date) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    reader = csv.DictReader(io.StringIO(raw_csv))
    _validate_required_columns(reader.fieldnames, required_columns=DAILY_DIMENSION_REQUIRED_CSV_COLUMNS)
    date_column = _resolve_daily_date_column(reader.fieldnames)
    for row in reader:
        if not any((value or "").strip() for value in row.values()):
            continue
        if (row.get(date_column) or "").strip() != report_date.isoformat():
            raise ValueError("Unexpected Ad Manager daily dimension report row date")
        site_name = _site_name_or_placeholder(row)
        country_code = (row.get("Dimension.COUNTRY_CODE") or "UNKNOWN").strip() or "UNKNOWN"
        ad_slot_id = (row.get("Dimension.AD_UNIT_ID") or "UNKNOWN").strip() or "UNKNOWN"
        rows.append({
            "report_date": report_date.isoformat(),
            "url_id": site_name,
            "url": site_name,
            "ad_country_code": country_code,
            "ad_country_name": country_code,
            "ad_slot_id": ad_slot_id,
            "ad_slot_name": ((row.get("Dimension.AD_UNIT_NAME") or ad_slot_id).strip() or ad_slot_id),
            "responses_served": _parse_int_or_zero_when_missing(row.get("Column.AD_EXCHANGE_RESPONSES_SERVED"), field_name="Column.AD_EXCHANGE_RESPONSES_SERVED"),
            "requests": _parse_int_or_zero_when_missing(row.get("Column.AD_EXCHANGE_TOTAL_REQUESTS"), field_name="Column.AD_EXCHANGE_TOTAL_REQUESTS"),
            "impressions": _parse_int_or_zero_when_missing(row.get("Column.AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS"), field_name="Column.AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS"),
            "clicks": _parse_int_or_zero_when_missing(row.get("Column.AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS"), field_name="Column.AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS"),
            "revenue": _parse_micros_or_zero_when_missing(row.get("Column.AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE"), field_name="Column.AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE"),
            "ecpm": _parse_micros_or_zero_when_missing(row.get("Column.AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM"), field_name="Column.AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM"),
        })
    return rows


def _validate_required_columns(fieldnames: list[str] | None, *, required_columns: tuple[str, ...] = REQUIRED_CSV_COLUMNS) -> None:
    seen = set(fieldnames or [])
    missing = [column_name for column_name in required_columns if column_name not in seen]
    if missing:
        raise ValueError(f"Ad Manager report CSV is missing required columns: {', '.join(missing)}")


def _resolve_daily_date_column(fieldnames: list[str] | None) -> str:
    seen = set(fieldnames or [])
    for column_name in DAILY_DATE_COLUMNS:
        if column_name in seen:
            return column_name
    raise ValueError(
        "Ad Manager report CSV is missing required columns: "
        + " or ".join(DAILY_DATE_COLUMNS)
    )


def _require_text(row: dict[str, str | None], field_name: str) -> str:
    text = (row.get(field_name) or "").strip()
    if text == "":
        raise ValueError(f"Missing required text cell value: {field_name}")
    return text


def _site_name_or_placeholder(row: dict[str, str | None]) -> str:
    text = (row.get("Dimension.SITE_NAME") or "").strip()
    if text != "":
        return text
    return MISSING_SITE_NAME_PLACEHOLDER


def _parse_int(value: str | None, *, field_name: str) -> int:
    text = (value or "").replace(",", "").strip()
    if text == "":
        raise ValueError(f"Missing required integer cell value: {field_name}")
    return _parse_non_empty_int(text, original_value=value)


def _parse_int_or_zero_when_missing(value: str | None, *, field_name: str) -> int:
    text = (value or "").replace(",", "").strip()
    if text == "":
        return 0
    return _parse_non_empty_int(text, original_value=value)


def _parse_non_empty_int(text: str, *, original_value: str | None) -> int:
    try:
        decimal_value = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid integer cell value: {original_value}") from exc
    if not decimal_value.is_finite():
        raise ValueError(f"Invalid integer cell value: {original_value}")
    if decimal_value != decimal_value.to_integral_value():
        raise ValueError(f"Invalid integer cell value: {original_value}")
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


def _parse_micros_or_zero_when_missing(value: str | None, *, field_name: str) -> str:
    text = (value or "").replace(",", "").strip()
    if text == "":
        return "0.000000"
    return _parse_micros_decimal_string(value, field_name=field_name)


def _parse_hour_value(value: str | None) -> int:
    hour = _parse_int(value, field_name="Dimension.HOUR")
    if hour < 0 or hour > 23:
        raise ValueError(f"Invalid hour cell value: {value}")
    return hour


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
        proxy_config: ProxyConfig | None = None,
        downloader_factory: Callable[[], Any] | None = None,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._network_code = network_code
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._application_name = application_name
        self._api_version = api_version
        self._timeout_seconds = timeout_seconds
        self._proxy_config = proxy_config
        self._report_definition = SoapReportDefinition()
        self._hourly_report_definition = HourlyDimensionSoapReportDefinition()
        self._daily_dimension_report_definition = DailyDimensionSoapReportDefinition()
        self._downloader_factory = downloader_factory
        self._client_factory = client_factory

    @property
    def report_definition(self) -> SoapReportDefinition:
        return self._report_definition

    @property
    def hourly_report_definition(self) -> HourlyDimensionSoapReportDefinition:
        return self._hourly_report_definition

    def fetch_rows(self, *, task_id: int, report_date: date) -> list[dict[str, object]]:
        return self._fetch_rows_with_definition(
            task_id=task_id,
            report_date=report_date,
            report_definition=self._report_definition,
            parser=lambda raw_csv: parse_report_csv(raw_csv, report_date=report_date),
        )

    def fetch_hourly_rows(self, *, task_id: int, report_date: date) -> list[dict[str, object]]:
        return self._fetch_rows_with_definition(
            task_id=task_id,
            report_date=report_date,
            report_definition=self._hourly_report_definition,
            parser=lambda raw_csv: parse_hourly_report_csv(
                raw_csv,
                report_date=report_date,
                source_timezone=self._hourly_report_definition.source_timezone,
            ),
        )

    def fetch_daily_dimension_rows(self, *, task_id: int, report_date: date) -> list[dict[str, object]]:
        return self._fetch_rows_with_definition(
            task_id=task_id,
            report_date=report_date,
            report_definition=self._daily_dimension_report_definition,
            parser=lambda raw_csv: parse_daily_dimension_report_csv(raw_csv, report_date=report_date),
        )

    def fetch_current_network(self) -> dict[str, str]:
        network_service = self._build_ad_manager_client().GetService(
            "NetworkService",
            version=self._api_version,
        )
        network = network_service.getCurrentNetwork()
        network_code = network.get("networkCode") if isinstance(network, dict) else getattr(network, "networkCode", None)
        timezone_name = network.get("timeZone") if isinstance(network, dict) else getattr(network, "timeZone", None)
        if not isinstance(network_code, str) or not network_code.strip():
            raise ValueError("Ad Manager current network did not include networkCode")
        if not isinstance(timezone_name, str) or not timezone_name.strip():
            raise ValueError("Ad Manager current network did not include timeZone")
        return {"network_code": network_code.strip(), "timezone": timezone_name.strip()}

    def fetch_network_timezone(self) -> str:
        return self.fetch_current_network()["timezone"]

    def _fetch_rows_with_definition(
        self,
        *,
        task_id: int,
        report_date: date,
        report_definition: SoapReportDefinition | HourlyDimensionSoapReportDefinition | DailyDimensionSoapReportDefinition,
        parser: Callable[[str], list[dict[str, object]]],
    ) -> list[dict[str, object]]:
        downloader = self._build_downloader()
        report_job_id = downloader.WaitForReport(
            {
                "reportQuery": report_definition.build_report_query(
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
        return parser(csv_io.getvalue().decode("utf-8", errors="ignore"))

    def _build_downloader(self) -> Any:
        if self._downloader_factory is not None:
            return self._downloader_factory()

        return self._build_ad_manager_client().GetDataDownloader(version=self._api_version)

    def _build_ad_manager_client(self) -> Any:
        if self._client_factory is not None:
            return self._client_factory()

        try:
            from googleads import ad_manager, common, oauth2
        except ImportError as exc:
            raise RuntimeError("googleads dependency is required for admanager_soap fetch mode") from exc

        googleads_proxy_config = _build_googleads_proxy_config(common=common, proxy_config=self._proxy_config)
        oauth2_client = oauth2.GoogleRefreshTokenClient(
            self._client_id,
            self._client_secret,
            self._refresh_token,
            proxy_config=googleads_proxy_config,
        )
        return ad_manager.AdManagerClient(
            oauth2_client,
            self._application_name,
            network_code=self._network_code,
            cache=None,
            proxy_config=googleads_proxy_config,
            timeout=self._timeout_seconds,
        )


def _build_googleads_proxy_config(*, common: Any, proxy_config: ProxyConfig | None) -> Any | None:
    if proxy_config is None:
        return None
    proxies = proxy_config.as_requests_proxies()
    return common.ProxyConfig(
        http_proxy=proxies.get("http"),
        https_proxy=proxies.get("https"),
    )
