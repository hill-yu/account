from __future__ import annotations

from datetime import date

from app.adx_report_service import AdxHourlyReportRow
from app.fetcher import AdManagerSoapReportFetcher
from app.models import CollectorTask, FetchBatch
from app.proxy import ProxyConfig


class FakeSoapService:
    def __init__(self) -> None:
        self.daily_calls: list[tuple[date, int]] = []
        self.daily_dimension_calls: list[tuple[date, int]] = []
        self.hourly_calls: list[tuple[date, int]] = []

    def fetch_site_daily_report(self, *, report_date: date, task_id: int = 1):
        self.daily_calls.append((report_date, task_id))
        return ["daily-row"]

    def fetch_site_daily_dimension_report(self, *, report_date: date, task_id: int = 1):
        self.daily_dimension_calls.append((report_date, task_id))
        return ["daily-dimension-row"]

    def build_authoritative_daily_fetch_batch(self, *, core_rows, dimension_rows, batch_key: str = "snapshot"):
        assert core_rows == ["daily-row"]
        assert dimension_rows == ["daily-dimension-row"]
        return FetchBatch(
            batch_key=batch_key,
            row_count=2,
            payload_hash="daily-hash",
            schema_version="admanager_authoritative_daily_v1",
            rows=[{"core_rows": [{"report_date": "2026-06-25"}], "dimension_rows": [{"report_date": "2026-06-25"}]}],
        )

    def fetch_site_hourly_report(self, *, report_date: date, task_id: int = 1):
        self.hourly_calls.append((report_date, task_id))
        return [
            AdxHourlyReportRow(
                report_date=report_date.isoformat(),
                hour=16,
                source_timezone="America/Los_Angeles",
                site_name="example.com",
                ad_country_code="US",
                ad_country_name="US",
                ad_slot_id="slot-1",
                ad_slot_name="Top Banner",
                responses_served=10,
                requests=12,
                impressions=8,
                clicks=1,
                revenue="1.000000",
                ecpm="125.000000",
            )
        ]

    def build_hourly_fetch_batch(
        self,
        *,
        rows,
        batch_key: str = "page-1",
        merge_mode: str = "append",
        touched_hours: list[int] | None = None,
        expected_hour_count: int | None = None,
    ):
        assert len(rows) == 1
        assert rows[0].source_timezone == "America/Los_Angeles"
        assert merge_mode == "replace_touched_hours"
        assert touched_hours
        assert expected_hour_count == 24
        return FetchBatch(
            batch_key=batch_key,
            row_count=1,
            payload_hash="hourly-hash",
            schema_version="admanager_hourly_dimension_v1",
            rows=[{"report_date": "2026-06-25", "hour": 16}],
        )


def test_admanager_soap_fetcher_uses_daily_batch_for_report_fetch() -> None:
    service = FakeSoapService()
    fetcher = AdManagerSoapReportFetcher(
        network_code="1234567",
        client_id="client-id",
        client_secret="client-secret",
        refresh_token="refresh-token",
        service=service,
    )
    task = CollectorTask(
        id=21,
        account_id=7,
        collector_instance_id=7,
        task_type="report_fetch",
        report_date=date(2026, 6, 25),
        status="in_progress",
    )

    batches = list(fetcher.fetch(task))

    assert len(batches) == 1
    assert batches[0].schema_version == "admanager_authoritative_daily_v1"
    assert service.daily_calls == [(date(2026, 6, 25), 21)]
    assert service.daily_dimension_calls == [(date(2026, 6, 25), 21)]
    assert service.hourly_calls == []


def test_admanager_soap_fetcher_uses_hourly_batch_for_report_fetch_hourly() -> None:
    service = FakeSoapService()
    fetcher = AdManagerSoapReportFetcher(
        network_code="1234567",
        client_id="client-id",
        client_secret="client-secret",
        refresh_token="refresh-token",
        service=service,
    )
    task = CollectorTask(
        id=22,
        account_id=7,
        collector_instance_id=7,
        task_type="report_fetch_hourly",
        report_date=date(2026, 6, 25),
        status="in_progress",
    )

    batches = list(fetcher.fetch(task))

    assert len(batches) == 1
    assert batches[0].schema_version == "admanager_hourly_dimension_v1"
    assert service.daily_calls == []
    assert service.daily_dimension_calls == []
    assert service.hourly_calls == [(date(2026, 6, 25), 22)]


def test_admanager_soap_fetcher_passes_proxy_config_when_building_default_service() -> None:
    proxy_config = ProxyConfig(
        protocol="socks5",
        host="proxy.example.com",
        port=5001,
        username="proxy-user",
        password="proxy-pass",
        expected_egress_ip="203.0.113.10",
    )

    fetcher = AdManagerSoapReportFetcher(
        network_code="1234567",
        client_id="client-id",
        client_secret="client-secret",
        refresh_token="refresh-token",
        proxy_config=proxy_config,
    )

    assert fetcher._service._proxy_config == proxy_config
