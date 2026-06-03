from __future__ import annotations

from datetime import date

import pytest

from app.admanager_soap import SoapReportDefinition, parse_report_csv


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
