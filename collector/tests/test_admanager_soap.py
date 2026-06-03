from __future__ import annotations

import io
from datetime import date

import pytest

from app.admanager_soap import AdManagerSoapClient, SoapReportDefinition, parse_report_csv


def test_soap_report_definition_builds_expected_query() -> None:
    definition = SoapReportDefinition()

    query = definition.build_report_query(task_id=7, report_date=date(2026, 6, 3))

    assert query == {
        "dimensions": ["DATE_PT", "URL_ID", "URL_NAME"],
        "columns": [
            "AD_EXCHANGE_RESPONSES_SERVED",
            "AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS",
            "AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS",
            "AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE",
            "AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM",
        ],
        "dateRangeType": "CUSTOM_DATE",
        "startDate": {"year": 2026, "month": 6, "day": 3},
        "endDate": {"year": 2026, "month": 6, "day": 3},
        "reportType": "HISTORICAL",
        "timeZoneType": "PACIFIC",
    }


def test_parse_report_csv_normalizes_adx_url_rows() -> None:
    raw_csv = """Dimension.DATE_PT,Dimension.URL_ID,Dimension.URL_NAME,Column.AD_EXCHANGE_RESPONSES_SERVED,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM
2026-06-03,2001,https://example.com/a,1000,950,15,12.345678,12.995450
2026-06-03,2002,https://example.com/b,800,760,8,4.250000,5.592105
"""

    rows = parse_report_csv(raw_csv, report_date=date(2026, 6, 3))

    assert rows == [
        {
            "report_date": "2026-06-03",
            "url_id": "2001",
            "url": "https://example.com/a",
            "responses_served": 1000,
            "impressions": 950,
            "clicks": 15,
            "revenue": "12.345678",
            "ecpm": "12.995450",
        },
        {
            "report_date": "2026-06-03",
            "url_id": "2002",
            "url": "https://example.com/b",
            "responses_served": 800,
            "impressions": 760,
            "clicks": 8,
            "revenue": "4.250000",
            "ecpm": "5.592105",
        },
    ]


def test_parse_report_csv_rejects_mismatched_row_date() -> None:
    raw_csv = """Dimension.DATE_PT,Dimension.URL_ID,Dimension.URL_NAME,Column.AD_EXCHANGE_RESPONSES_SERVED,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM
2026-06-02,2001,https://example.com/a,1000,950,15,12.345678,12.995450
"""

    with pytest.raises(ValueError, match="Unexpected Ad Manager report row date"):
        parse_report_csv(raw_csv, report_date=date(2026, 6, 3))


def test_parse_report_csv_rejects_invalid_integer_values() -> None:
    raw_csv = """Dimension.DATE_PT,Dimension.URL_ID,Dimension.URL_NAME,Column.AD_EXCHANGE_RESPONSES_SERVED,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM
2026-06-03,2001,https://example.com/a,1.9,950,15,12.345678,12.995450
"""

    with pytest.raises(ValueError, match="Invalid integer cell value"):
        parse_report_csv(raw_csv, report_date=date(2026, 6, 3))


def test_parse_report_csv_rejects_missing_required_columns() -> None:
    raw_csv = """Dimension.DATE_PT,Dimension.URL_ID,Column.AD_EXCHANGE_RESPONSES_SERVED,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM
2026-06-03,2001,1000,950,15,12.345678,12.995450
"""

    with pytest.raises(ValueError, match="missing required columns"):
        parse_report_csv(raw_csv, report_date=date(2026, 6, 3))


def test_parse_report_csv_rejects_truncated_rows() -> None:
    raw_csv = """Dimension.DATE_PT,Dimension.URL_ID,Dimension.URL_NAME,Column.AD_EXCHANGE_RESPONSES_SERVED,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM
2026-06-03,2001,https://example.com/a,1000,950,15,12.345678,
"""

    with pytest.raises(ValueError, match="Missing required decimal cell value"):
        parse_report_csv(raw_csv, report_date=date(2026, 6, 3))


def test_parse_report_csv_supports_comma_formatted_numeric_input() -> None:
    raw_csv = """Dimension.DATE_PT,Dimension.URL_ID,Dimension.URL_NAME,Column.AD_EXCHANGE_RESPONSES_SERVED,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM
2026-06-03,2001,https://example.com/a,"1,000","950","15","12,345.678901","12,995.450000"
"""

    rows = parse_report_csv(raw_csv, report_date=date(2026, 6, 3))

    assert rows == [
        {
            "report_date": "2026-06-03",
            "url_id": "2001",
            "url": "https://example.com/a",
            "responses_served": 1000,
            "impressions": 950,
            "clicks": 15,
            "revenue": "12345.678901",
            "ecpm": "12995.450000",
        }
    ]


def test_parse_report_csv_rejects_non_finite_decimal_values() -> None:
    raw_csv = """Dimension.DATE_PT,Dimension.URL_ID,Dimension.URL_NAME,Column.AD_EXCHANGE_RESPONSES_SERVED,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM
2026-06-03,2001,https://example.com/a,1000,950,15,NaN,12.995450
"""

    with pytest.raises(ValueError, match="Invalid decimal cell value"):
        parse_report_csv(raw_csv, report_date=date(2026, 6, 3))


class FakeDownloader:
    def __init__(self) -> None:
        self.wait_calls: list[tuple[dict[str, object], int]] = []
        self.download_calls: list[tuple[int, str, bool, bool, bool]] = []

    def WaitForReport(self, report_job: dict[str, object], poll_time_seconds: int) -> int:
        self.wait_calls.append((report_job, poll_time_seconds))
        return 12345

    def DownloadReportToFile(
        self,
        report_job_id: int,
        export_format: str,
        outfile: io.BytesIO,
        include_report_properties: bool,
        include_totals_row: bool,
        use_gzip_compression: bool,
    ) -> None:
        self.download_calls.append(
            (
                report_job_id,
                export_format,
                include_report_properties,
                include_totals_row,
                use_gzip_compression,
            )
        )
        outfile.write(
            b"Dimension.DATE_PT,Dimension.URL_ID,Dimension.URL_NAME,Column.AD_EXCHANGE_RESPONSES_SERVED,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM\n"
            b"2026-06-03,2001,https://example.com/a,1000,950,15,12.345678,12.995450\n"
        )


def test_admanager_soap_client_downloads_and_parses_rows() -> None:
    downloader = FakeDownloader()
    client = AdManagerSoapClient(
        network_code="1234567",
        client_id="client-id",
        client_secret="client-secret",
        refresh_token="refresh-token",
        application_name="adx-account-isolated-collector",
        api_version="v202602",
        downloader_factory=lambda: downloader,
    )

    rows = client.fetch_rows(task_id=7, report_date=date(2026, 6, 3))

    assert rows == [
        {
            "report_date": "2026-06-03",
            "url_id": "2001",
            "url": "https://example.com/a",
            "responses_served": 1000,
            "impressions": 950,
            "clicks": 15,
            "revenue": "12.345678",
            "ecpm": "12.995450",
        }
    ]
    assert downloader.wait_calls == [
        (
            {"reportQuery": SoapReportDefinition().build_report_query(task_id=7, report_date=date(2026, 6, 3))},
            2,
        )
    ]
    assert downloader.download_calls == [
        (12345, "CSV_DUMP", False, False, False)
    ]
