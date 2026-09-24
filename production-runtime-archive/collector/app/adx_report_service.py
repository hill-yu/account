from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import hashlib
import json
from typing import Callable
from zoneinfo import ZoneInfo

from app.admanager_soap import AdManagerSoapClient
from app.models import FetchBatch
from app.proxy import ProxyConfig


@dataclass(frozen=True)
class AdxApiCredentials:
    network_code: str
    client_id: str
    client_secret: str
    refresh_token: str


@dataclass(frozen=True)
class AdxReportRow:
    report_date: str
    site_name: str
    responses_served: int
    requests: int
    impressions: int
    clicks: int
    revenue: str
    ecpm: str

    def as_collector_row(self) -> dict[str, object]:
        return {
            "report_date": self.report_date,
            "url_id": self.site_name,
            "url": self.site_name,
            "responses_served": self.responses_served,
            "requests": self.requests,
            "impressions": self.impressions,
            "clicks": self.clicks,
            "revenue": self.revenue,
            "ecpm": self.ecpm,
        }


@dataclass(frozen=True)
class AdxHourlyReportRow:
    report_date: str
    hour: int
    source_timezone: str
    site_name: str
    ad_country_code: str
    ad_country_name: str
    ad_slot_id: str
    ad_slot_name: str
    responses_served: int
    requests: int
    impressions: int
    clicks: int
    revenue: str
    ecpm: str

    def as_collector_row(self) -> dict[str, object]:
        return {
            "report_date": self.report_date,
            "hour": self.hour,
            "source_timezone": self.source_timezone,
            "url_id": self.site_name,
            "url": self.site_name,
            "ad_country_code": self.ad_country_code,
            "ad_country_name": self.ad_country_name,
            "ad_slot_id": self.ad_slot_id,
            "ad_slot_name": self.ad_slot_name,
            "responses_served": self.responses_served,
            "requests": self.requests,
            "impressions": self.impressions,
            "clicks": self.clicks,
            "revenue": self.revenue,
            "ecpm": self.ecpm,
        }


@dataclass(frozen=True)
class AdxDailyDimensionReportRow:
    report_date: str; site_name: str; ad_country_code: str; ad_country_name: str; ad_slot_id: str; ad_slot_name: str
    responses_served: int; requests: int; impressions: int; clicks: int; revenue: str; ecpm: str
    def as_collector_row(self) -> dict[str, object]:
        return {"report_date": self.report_date, "url_id": self.site_name, "url": self.site_name, "ad_country_code": self.ad_country_code, "ad_country_name": self.ad_country_name, "ad_slot_id": self.ad_slot_id, "ad_slot_name": self.ad_slot_name, "responses_served": self.responses_served, "requests": self.requests, "impressions": self.impressions, "clicks": self.clicks, "revenue": self.revenue, "ecpm": self.ecpm}


class AdxReportService:
    def __init__(
        self,
        *,
        credentials: AdxApiCredentials,
        proxy_config: ProxyConfig | None = None,
        soap_client_factory: Callable[[AdxApiCredentials], object] | None = None,
    ) -> None:
        self._credentials = credentials
        self._proxy_config = proxy_config
        self._soap_client_factory = soap_client_factory

    def fetch_network_timezone(self) -> str:
        return self._build_soap_client().fetch_network_timezone()

    def fetch_site_daily_report(self, *, report_date: date, task_id: int = 1) -> list[AdxReportRow]:
        soap_client = self._build_soap_client()
        rows = soap_client.fetch_rows(task_id=task_id, report_date=report_date)
        return [_row_from_collector_dict(row) for row in rows]

    def fetch_site_daily_dimension_report(self, *, report_date: date, task_id: int = 1) -> list[AdxDailyDimensionReportRow]:
        rows = self._build_soap_client().fetch_daily_dimension_rows(task_id=task_id, report_date=report_date)
        return [_daily_dimension_row_from_collector_dict(row) for row in rows]

    def build_daily_dimension_fetch_batch(self, *, rows: list[AdxDailyDimensionReportRow], batch_key: str = "page-1") -> FetchBatch | None:
        if not rows: return None
        collector_rows = [row.as_collector_row() for row in rows]
        return FetchBatch(batch_key=batch_key, row_count=len(collector_rows), payload_hash=_hash_rows(collector_rows), schema_version="admanager_daily_dimension_v1", rows=collector_rows)

    def fetch_site_daily_range(
        self,
        *,
        start_date: date,
        end_date: date,
    ) -> list[AdxReportRow]:
        if end_date < start_date:
            raise ValueError("end_date must be on or after start_date")
        rows: list[AdxReportRow] = []
        current = start_date
        task_id = 1
        while current <= end_date:
            rows.extend(self.fetch_site_daily_report(report_date=current, task_id=task_id))
            current += timedelta(days=1)
            task_id += 1
        return rows

    def fetch_site_hourly_report(self, *, report_date: date, task_id: int = 1) -> list[AdxHourlyReportRow]:
        soap_client = self._build_soap_client()
        rows = soap_client.fetch_hourly_rows(task_id=task_id, report_date=report_date)
        return [_hourly_row_from_collector_dict(row) for row in rows]

    def fetch_site_daily_rows_as_dicts(
        self,
        *,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, object]]:
        return [row.as_collector_row() for row in self.fetch_site_daily_range(start_date=start_date, end_date=end_date)]

    def build_fetch_batch(
        self,
        *,
        rows: list[AdxReportRow],
        batch_key: str = "page-1",
    ) -> FetchBatch | None:
        if not rows:
            return None
        collector_rows = [row.as_collector_row() for row in rows]
        return FetchBatch(
            batch_key=batch_key,
            row_count=len(collector_rows),
            payload_hash=_hash_rows(collector_rows),
            schema_version="admanager_site_core_v1",
            rows=collector_rows,
        )

    def build_hourly_fetch_batch(
        self,
        *,
        rows: list[AdxHourlyReportRow],
        batch_key: str = "page-1",
        merge_mode: str | None = None,
        touched_hours: list[int] | None = None,
        expected_hour_count: int | None = None,
    ) -> FetchBatch | None:
        if not rows and touched_hours is None:
            return None
        collector_rows = [row.as_collector_row() for row in rows]
        normalized_touched_hours = touched_hours
        normalized_expected_hour_count = expected_hour_count
        if rows:
            source_timezone = rows[0].source_timezone
            if normalized_touched_hours is None:
                normalized_touched_hours = sorted({row.hour for row in rows})
            if normalized_expected_hour_count is None:
                normalized_expected_hour_count = _expected_hour_count_for_report_date(
                    report_date=date.fromisoformat(rows[0].report_date),
                    source_timezone=source_timezone,
                )
        return FetchBatch(
            batch_key=batch_key,
            row_count=len(collector_rows),
            payload_hash=_hash_rows(collector_rows),
            schema_version="admanager_hourly_dimension_v1",
            merge_mode=merge_mode or "replace_touched_hours",
            touched_hours=normalized_touched_hours,
            expected_hour_count=normalized_expected_hour_count or 24,
            rows=collector_rows,
        )

    def _build_soap_client(self) -> object:
        if self._soap_client_factory is not None:
            return self._soap_client_factory(self._credentials)
        return AdManagerSoapClient(
            network_code=self._credentials.network_code,
            client_id=self._credentials.client_id,
            client_secret=self._credentials.client_secret,
            refresh_token=self._credentials.refresh_token,
            proxy_config=self._proxy_config,
        )


def _row_from_collector_dict(row: dict[str, object]) -> AdxReportRow:
    return AdxReportRow(
        report_date=str(row["report_date"]),
        site_name=str(row["url"]),
        responses_served=int(row["responses_served"]),
        requests=int(row["requests"]),
        impressions=int(row["impressions"]),
        clicks=int(row["clicks"]),
        revenue=str(row["revenue"]),
        ecpm=str(row["ecpm"]),
    )


def _daily_dimension_row_from_collector_dict(row: dict[str, object]) -> AdxDailyDimensionReportRow:
    return AdxDailyDimensionReportRow(
        report_date=str(row["report_date"]), site_name=str(row["url"]),
        ad_country_code=str(row["ad_country_code"]), ad_country_name=str(row["ad_country_name"]),
        ad_slot_id=str(row["ad_slot_id"]), ad_slot_name=str(row["ad_slot_name"]),
        responses_served=int(row["responses_served"]), requests=int(row["requests"]),
        impressions=int(row["impressions"]), clicks=int(row["clicks"]),
        revenue=str(row["revenue"]), ecpm=str(row["ecpm"]),
    )


def _hourly_row_from_collector_dict(row: dict[str, object]) -> AdxHourlyReportRow:
    return AdxHourlyReportRow(
        report_date=str(row["report_date"]),
        hour=int(row["hour"]),
        source_timezone=str(row["source_timezone"]),
        site_name=str(row["url"]),
        ad_country_code=str(row["ad_country_code"]),
        ad_country_name=str(row["ad_country_name"]),
        ad_slot_id=str(row["ad_slot_id"]),
        ad_slot_name=str(row["ad_slot_name"]),
        responses_served=int(row["responses_served"]),
        requests=int(row["requests"]),
        impressions=int(row["impressions"]),
        clicks=int(row["clicks"]),
        revenue=str(row["revenue"]),
        ecpm=str(row["ecpm"]),
    )


def _hash_rows(rows: list[dict[str, object]]) -> str:
    return hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _expected_hour_count_for_report_date(*, report_date: date, source_timezone: str) -> int:
    timezone = ZoneInfo(source_timezone)
    local_start = datetime(report_date.year, report_date.month, report_date.day, tzinfo=timezone)
    next_local_start = local_start + timedelta(days=1)
    utc_delta = next_local_start.astimezone(ZoneInfo("UTC")) - local_start.astimezone(ZoneInfo("UTC"))
    return int(utc_delta.total_seconds() // 3600)
