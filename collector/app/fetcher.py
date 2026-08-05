from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
import hashlib
import json
from typing import Callable, Protocol
from zoneinfo import ZoneInfo

import requests

from app.admanager_api import AdManagerApiClient
from app.adx_report_service import AdxApiCredentials, AdxHourlyReportRow, AdxReportService, _expected_hour_count_for_report_date
from app.models import CollectorTask, FetchBatch
from app.oauth import refresh_access_token
from app.models import RuntimeSettings
from app.proxy import ProxyConfig

DEFAULT_SOURCE_TIMEZONE = "America/Los_Angeles"


class Fetcher(Protocol):
    def fetch(self, task: CollectorTask) -> Iterable[FetchBatch]:
        ...


class StubFetcher:
    def fetch(self, task: CollectorTask) -> Iterable[FetchBatch]:
        rows = [
            {
                "report_date": task.report_date.isoformat(),
                "url_id": "stub-url-1",
                "url": "https://stub.example.com/",
                "responses_served": 1200,
                "impressions": 1000,
                "clicks": 12,
                "revenue": "15.500000",
                "ecpm": "15.500000",
            },
            {
                "report_date": task.report_date.isoformat(),
                "url_id": "stub-url-2",
                "url": "https://stub.example.com/news",
                "responses_served": 800,
                "impressions": 650,
                "clicks": 7,
                "revenue": "6.500000",
                "ecpm": "10.000000",
            },
        ]
        return (
            FetchBatch(
                batch_key="page-1",
                row_count=len(rows),
                payload_hash=_hash_rows(rows),
                schema_version="admanager_site_core_v1",
                rows=rows,
            ),
        )


class AdManagerRestReportFetcher:
    def __init__(
        self,
        *,
        network_code: str,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        timeout_seconds: int = 30,
        session: requests.Session | object | None = None,
        poll_interval_seconds: float = 1.0,
        page_size: int = 500,
    ) -> None:
        self._network_code = network_code
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._timeout_seconds = timeout_seconds
        self._session = session or requests.Session()
        self._poll_interval_seconds = poll_interval_seconds
        self._page_size = page_size

    def fetch(self, task: CollectorTask) -> Iterable[FetchBatch]:
        access_token = refresh_access_token(
            client_id=self._client_id,
            client_secret=self._client_secret,
            refresh_token=self._refresh_token,
            timeout_seconds=self._timeout_seconds,
            session=self._session,
        )
        api_client = AdManagerApiClient(
            network_code=self._network_code,
            access_token=access_token,
            timeout_seconds=self._timeout_seconds,
            session=self._session,
            poll_interval_seconds=self._poll_interval_seconds,
            page_size=self._page_size,
        )
        for page_number, rows in enumerate(api_client.iter_report_rows(task), start=1):
            yield FetchBatch(
                batch_key=f"page-{page_number}",
                row_count=len(rows),
                payload_hash=_hash_rows(rows),
                schema_version=api_client.report_definition.schema_version,
                rows=rows,
            )


class AdManagerSoapReportFetcher:
    def __init__(
        self,
        *,
        network_code: str,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        proxy_config: ProxyConfig | None = None,
        service: AdxReportService | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._service = service or AdxReportService(
            credentials=AdxApiCredentials(
                network_code=network_code,
                client_id=client_id,
                client_secret=client_secret,
                refresh_token=refresh_token,
            ),
            proxy_config=proxy_config,
        )
        self._now_provider = now_provider or (lambda: datetime.now(UTC))

    def fetch(self, task: CollectorTask) -> Iterable[FetchBatch]:
        if task.task_type == "report_fetch_hourly":
            rows = self._service.fetch_site_hourly_report(report_date=task.report_date, task_id=task.id)
            source_timezone = _resolve_source_timezone(rows)
            expected_hour_count = _expected_hour_count_for_report_date(
                report_date=task.report_date,
                source_timezone=source_timezone,
            )
            touched_hours = _build_touched_hours(
                task=task,
                source_timezone=source_timezone,
                expected_hour_count=expected_hour_count,
                now=self._now_provider(),
            )
            batch = self._service.build_hourly_fetch_batch(
                rows=rows,
                merge_mode="replace_touched_hours",
                touched_hours=touched_hours,
                expected_hour_count=expected_hour_count,
            )
            if batch is None:
                return ()
            return (batch,)
        rows = self._service.fetch_site_daily_report(report_date=task.report_date, task_id=task.id)
        batch = self._service.build_fetch_batch(rows=rows)
        if batch is None:
            return ()
        return (batch,)


def build_fetcher(settings: RuntimeSettings) -> Fetcher:
    if settings.fetch_mode == "stub":
        return StubFetcher()
    if settings.fetch_mode == "admanager_rest":
        return AdManagerRestReportFetcher(
            network_code=_require_setting(settings.admanager_network_code, "admanager_network_code"),
            client_id=_require_setting(settings.google_oauth_client_id, "google_oauth_client_id"),
            client_secret=_require_setting(settings.google_oauth_client_secret, "google_oauth_client_secret"),
            refresh_token=_require_setting(settings.google_oauth_refresh_token, "google_oauth_refresh_token"),
            timeout_seconds=settings.request_timeout_seconds,
        )
    if settings.fetch_mode == "admanager_soap":
        return AdManagerSoapReportFetcher(
            network_code=_require_setting(settings.admanager_network_code, "admanager_network_code"),
            client_id=_require_setting(settings.google_oauth_client_id, "google_oauth_client_id"),
            client_secret=_require_setting(settings.google_oauth_client_secret, "google_oauth_client_secret"),
            refresh_token=_require_setting(settings.google_oauth_refresh_token, "google_oauth_refresh_token"),
            proxy_config=ProxyConfig(
                protocol=settings.proxy_protocol,
                host=settings.proxy_host,
                port=settings.proxy_port,
                username=settings.proxy_username,
                password=settings.proxy_password,
                expected_egress_ip=settings.expected_egress_ip,
            ),
        )
    raise ValueError(f"Unsupported fetch mode: {settings.fetch_mode}")


def _hash_rows(rows: list[dict[str, object]]) -> str:
    return hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _resolve_source_timezone(rows: list[AdxHourlyReportRow]) -> str:
    if rows:
        return rows[0].source_timezone
    return DEFAULT_SOURCE_TIMEZONE


def _build_touched_hours(
    *,
    task: CollectorTask,
    source_timezone: str,
    expected_hour_count: int,
    now: datetime,
) -> list[int]:
    if task.run_reason in {"finalize", "repair"}:
        return list(range(expected_hour_count))

    localized_now = now.astimezone(ZoneInfo(source_timezone))
    if task.report_date < localized_now.date():
        return list(range(expected_hour_count))
    if task.report_date > localized_now.date():
        return []
    completed_hours = max(localized_now.hour - 1, -1)
    if completed_hours < 0:
        return []
    return list(range(completed_hours + 1))


def _require_setting(value: str | None, field_name: str) -> str:
    if value is None or value == "":
        raise ValueError(f"Missing runtime setting: {field_name}")
    return value
