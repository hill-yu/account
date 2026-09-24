from __future__ import annotations

from datetime import date

from app.models import FetchBatch


def test_fetch_site_daily_report_returns_typed_rows() -> None:
    from app.adx_report_service import AdxApiCredentials, AdxReportRow, AdxReportService

    class FakeSoapClient:
        def __init__(self) -> None:
            self.calls: list[tuple[int, date]] = []

        def fetch_rows(self, *, task_id: int, report_date: date) -> list[dict[str, object]]:
            self.calls.append((task_id, report_date))
            return [
                {
                    "report_date": "2026-05-14",
                    "url_id": "jane.ghfkl.com",
                    "url": "jane.ghfkl.com",
                    "responses_served": 34,
                    "requests": 40,
                    "impressions": 33,
                    "clicks": 4,
                    "revenue": "7.646800",
                    "ecpm": "231.721203",
                }
            ]

    soap_client = FakeSoapClient()
    service = AdxReportService(
        credentials=AdxApiCredentials(
            network_code="23347208010",
            client_id="client-id",
            client_secret="client-secret",
            refresh_token="refresh-token",
        ),
        soap_client_factory=lambda credentials: soap_client,
    )

    rows = service.fetch_site_daily_report(report_date=date(2026, 5, 14))

    assert rows == [
        AdxReportRow(
            report_date="2026-05-14",
            site_name="jane.ghfkl.com",
            responses_served=34,
            requests=40,
            impressions=33,
            clicks=4,
            revenue="7.646800",
            ecpm="231.721203",
        )
    ]
    assert soap_client.calls == [(1, date(2026, 5, 14))]


def test_fetch_site_daily_range_aggregates_days() -> None:
    from app.adx_report_service import AdxApiCredentials, AdxReportService

    class FakeSoapClient:
        def fetch_rows(self, *, task_id: int, report_date: date) -> list[dict[str, object]]:
            return [
                {
                    "report_date": report_date.isoformat(),
                    "url_id": f"site-{report_date.isoformat()}",
                    "url": f"site-{report_date.isoformat()}",
                    "responses_served": 1,
                    "requests": 6,
                    "impressions": 2,
                    "clicks": 3,
                    "revenue": "4.000000",
                    "ecpm": "5.000000",
                }
            ]

    service = AdxReportService(
        credentials=AdxApiCredentials(
            network_code="23347208010",
            client_id="client-id",
            client_secret="client-secret",
            refresh_token="refresh-token",
        ),
        soap_client_factory=lambda credentials: FakeSoapClient(),
    )

    rows = service.fetch_site_daily_range(start_date=date(2026, 5, 14), end_date=date(2026, 5, 15))

    assert [row.report_date for row in rows] == ["2026-05-14", "2026-05-15"]
    assert [row.site_name for row in rows] == ["site-2026-05-14", "site-2026-05-15"]


def test_fetch_site_daily_rows_as_dicts_matches_current_collector_shape() -> None:
    from app.adx_report_service import AdxApiCredentials, AdxReportService

    class FakeSoapClient:
        def fetch_rows(self, *, task_id: int, report_date: date) -> list[dict[str, object]]:
            return [
                {
                    "report_date": "2026-05-14",
                    "url_id": "jane.ghfkl.com",
                    "url": "jane.ghfkl.com",
                    "responses_served": 34,
                    "requests": 40,
                    "impressions": 33,
                    "clicks": 4,
                    "revenue": "7.646800",
                    "ecpm": "231.721203",
                }
            ]

    service = AdxReportService(
        credentials=AdxApiCredentials(
            network_code="23347208010",
            client_id="client-id",
            client_secret="client-secret",
            refresh_token="refresh-token",
        ),
        soap_client_factory=lambda credentials: FakeSoapClient(),
    )

    rows = service.fetch_site_daily_rows_as_dicts(start_date=date(2026, 5, 14), end_date=date(2026, 5, 14))

    assert rows == [
        {
            "report_date": "2026-05-14",
            "url_id": "jane.ghfkl.com",
            "url": "jane.ghfkl.com",
            "responses_served": 34,
            "requests": 40,
            "impressions": 33,
            "clicks": 4,
            "revenue": "7.646800",
            "ecpm": "231.721203",
        }
    ]


def test_build_fetch_batch_returns_compatibility_batch() -> None:
    from app.adx_report_service import AdxApiCredentials, AdxReportRow, AdxReportService

    service = AdxReportService(
        credentials=AdxApiCredentials(
            network_code="23347208010",
            client_id="client-id",
            client_secret="client-secret",
            refresh_token="refresh-token",
        )
    )

    batch = service.build_fetch_batch(
        rows=[
            AdxReportRow(
                report_date="2026-05-14",
                site_name="jane.ghfkl.com",
                responses_served=34,
                requests=40,
                impressions=33,
                clicks=4,
                revenue="7.646800",
                ecpm="231.721203",
            )
        ]
    )

    assert batch == FetchBatch(
        batch_key="page-1",
        row_count=1,
        payload_hash="3f070bf060a82026ee692ee0b30b7684fac16a26b1fc6299abce190215269f28",
        schema_version="admanager_site_core_v1",
        rows=[
            {
                "report_date": "2026-05-14",
                "url_id": "jane.ghfkl.com",
                "url": "jane.ghfkl.com",
                "responses_served": 34,
                "requests": 40,
                "impressions": 33,
                "clicks": 4,
                "revenue": "7.646800",
                "ecpm": "231.721203",
            }
        ],
    )
