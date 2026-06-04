from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import hashlib
import json
from typing import Callable

from app.admanager_soap import AdManagerSoapClient
from app.models import FetchBatch


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
            "impressions": self.impressions,
            "clicks": self.clicks,
            "revenue": self.revenue,
            "ecpm": self.ecpm,
        }


class AdxReportService:
    def __init__(
        self,
        *,
        credentials: AdxApiCredentials,
        soap_client_factory: Callable[[AdxApiCredentials], object] | None = None,
    ) -> None:
        self._credentials = credentials
        self._soap_client_factory = soap_client_factory

    def fetch_site_daily_report(self, *, report_date: date, task_id: int = 1) -> list[AdxReportRow]:
        soap_client = self._build_soap_client()
        rows = soap_client.fetch_rows(task_id=task_id, report_date=report_date)
        return [_row_from_collector_dict(row) for row in rows]

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

    def _build_soap_client(self) -> object:
        if self._soap_client_factory is not None:
            return self._soap_client_factory(self._credentials)
        return AdManagerSoapClient(
            network_code=self._credentials.network_code,
            client_id=self._credentials.client_id,
            client_secret=self._credentials.client_secret,
            refresh_token=self._credentials.refresh_token,
        )


def _row_from_collector_dict(row: dict[str, object]) -> AdxReportRow:
    return AdxReportRow(
        report_date=str(row["report_date"]),
        site_name=str(row["url"]),
        responses_served=int(row["responses_served"]),
        impressions=int(row["impressions"]),
        clicks=int(row["clicks"]),
        revenue=str(row["revenue"]),
        ecpm=str(row["ecpm"]),
    )


def _hash_rows(rows: list[dict[str, object]]) -> str:
    return hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
