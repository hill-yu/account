from __future__ import annotations

import io
import sys
import types
from datetime import date

import pytest

from app.admanager_soap import AdManagerSoapClient, SoapReportDefinition, parse_report_csv
from app.proxy import ProxyConfig


def test_soap_report_definition_builds_expected_query() -> None:
    definition = SoapReportDefinition()

    query = definition.build_report_query(task_id=7, report_date=date(2026, 6, 3))

    assert query == {
        "dimensions": ["DATE_PT", "SITE_NAME"],
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
        "timeZoneType": "PACIFIC",
    }


def test_parse_report_csv_normalizes_adx_url_rows() -> None:
    raw_csv = """Dimension.DATE_PT,Dimension.SITE_NAME,Column.AD_EXCHANGE_RESPONSES_SERVED,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM
2026-06-03,jane.ghfkl.com,1000,950,15,12345678,12995450
2026-06-03,longan.ghfkl.com,800,760,8,4250000,5592105
"""

    rows = parse_report_csv(raw_csv, report_date=date(2026, 6, 3))

    assert rows == [
        {
            "report_date": "2026-06-03",
            "url_id": "jane.ghfkl.com",
            "url": "jane.ghfkl.com",
            "responses_served": 1000,
            "impressions": 950,
            "clicks": 15,
            "revenue": "12.345678",
            "ecpm": "12.995450",
        },
        {
            "report_date": "2026-06-03",
            "url_id": "longan.ghfkl.com",
            "url": "longan.ghfkl.com",
            "responses_served": 800,
            "impressions": 760,
            "clicks": 8,
            "revenue": "4.250000",
            "ecpm": "5.592105",
        },
    ]


def test_parse_report_csv_rejects_mismatched_row_date() -> None:
    raw_csv = """Dimension.DATE_PT,Dimension.SITE_NAME,Column.AD_EXCHANGE_RESPONSES_SERVED,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM
2026-06-02,jane.ghfkl.com,1000,950,15,12345678,12995450
"""

    with pytest.raises(ValueError, match="Unexpected Ad Manager report row date"):
        parse_report_csv(raw_csv, report_date=date(2026, 6, 3))


def test_parse_report_csv_rejects_invalid_integer_values() -> None:
    raw_csv = """Dimension.DATE_PT,Dimension.SITE_NAME,Column.AD_EXCHANGE_RESPONSES_SERVED,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM
2026-06-03,jane.ghfkl.com,1.9,950,15,12345678,12995450
"""

    with pytest.raises(ValueError, match="Invalid integer cell value"):
        parse_report_csv(raw_csv, report_date=date(2026, 6, 3))


def test_parse_report_csv_rejects_missing_required_columns() -> None:
    raw_csv = """Dimension.DATE_PT,Column.AD_EXCHANGE_RESPONSES_SERVED,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM
2026-06-03,1000,950,15,12345678,12995450
"""

    with pytest.raises(ValueError, match="missing required columns"):
        parse_report_csv(raw_csv, report_date=date(2026, 6, 3))


def test_parse_report_csv_rejects_truncated_rows() -> None:
    raw_csv = """Dimension.DATE_PT,Dimension.SITE_NAME,Column.AD_EXCHANGE_RESPONSES_SERVED,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM
2026-06-03,jane.ghfkl.com,1000,950,15,12345678,
"""

    with pytest.raises(ValueError, match="Missing required decimal cell value"):
        parse_report_csv(raw_csv, report_date=date(2026, 6, 3))


def test_parse_report_csv_supports_comma_formatted_numeric_input() -> None:
    raw_csv = """Dimension.DATE_PT,Dimension.SITE_NAME,Column.AD_EXCHANGE_RESPONSES_SERVED,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM
2026-06-03,jane.ghfkl.com,"1,000","950","15","12,345,678","12,995,450"
"""

    rows = parse_report_csv(raw_csv, report_date=date(2026, 6, 3))

    assert rows == [
        {
            "report_date": "2026-06-03",
            "url_id": "jane.ghfkl.com",
            "url": "jane.ghfkl.com",
            "responses_served": 1000,
            "impressions": 950,
            "clicks": 15,
            "revenue": "12.345678",
            "ecpm": "12.995450",
        }
    ]


def test_parse_report_csv_rejects_non_finite_decimal_values() -> None:
    raw_csv = """Dimension.DATE_PT,Dimension.SITE_NAME,Column.AD_EXCHANGE_RESPONSES_SERVED,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM
2026-06-03,jane.ghfkl.com,1000,950,15,NaN,12995450
"""

    with pytest.raises(ValueError, match="Invalid decimal cell value"):
        parse_report_csv(raw_csv, report_date=date(2026, 6, 3))


def test_parse_report_csv_normalizes_real_micros_values() -> None:
    raw_csv = """Dimension.DATE_PT,Dimension.SITE_NAME,Column.AD_EXCHANGE_RESPONSES_SERVED,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM
2026-05-14,jane.ghfkl.com,34,33,4,7646800,231721203
"""

    rows = parse_report_csv(raw_csv, report_date=date(2026, 5, 14))

    assert rows == [
        {
            "report_date": "2026-05-14",
            "url_id": "jane.ghfkl.com",
            "url": "jane.ghfkl.com",
            "responses_served": 34,
            "impressions": 33,
            "clicks": 4,
            "revenue": "7.646800",
            "ecpm": "231.721203",
        }
    ]


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
            b"Dimension.DATE_PT,Dimension.SITE_NAME,Column.AD_EXCHANGE_RESPONSES_SERVED,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM\n"
            b"2026-06-03,jane.ghfkl.com,1000,950,15,12345678,12995450\n"
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
            "url_id": "jane.ghfkl.com",
            "url": "jane.ghfkl.com",
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


def test_admanager_soap_client_passes_googleads_proxy_config(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakeGoogleadsProxyConfig:
        def __init__(self, *, http_proxy=None, https_proxy=None, cafile=None, disable_certificate_validation=False):
            self.proxies = {}
            if http_proxy is not None:
                self.proxies["http"] = http_proxy
            if https_proxy is not None:
                self.proxies["https"] = https_proxy
            self.cafile = cafile
            self.disable_certificate_validation = disable_certificate_validation

    class FakeOAuthClient:
        def __init__(self, client_id, client_secret, refresh_token, **kwargs):
            captured["oauth"] = {
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "kwargs": kwargs,
            }

    class FakeAdManagerClient:
        def __init__(self, oauth_client, application_name, **kwargs):
            captured["ad_manager"] = {
                "oauth_client": oauth_client,
                "application_name": application_name,
                "kwargs": kwargs,
            }

        def GetDataDownloader(self, version: str):
            captured["version"] = version
            return "fake-downloader"

    fake_googleads = types.ModuleType("googleads")
    fake_googleads.common = types.SimpleNamespace(ProxyConfig=FakeGoogleadsProxyConfig)
    fake_googleads.oauth2 = types.SimpleNamespace(GoogleRefreshTokenClient=FakeOAuthClient)
    fake_googleads.ad_manager = types.SimpleNamespace(AdManagerClient=FakeAdManagerClient)

    monkeypatch.setitem(sys.modules, "googleads", fake_googleads)

    client = AdManagerSoapClient(
        network_code="1234567",
        client_id="client-id",
        client_secret="client-secret",
        refresh_token="refresh-token",
        application_name="adx-account-isolated-collector",
        api_version="v202602",
        proxy_config=ProxyConfig(
            protocol="http",
            host="proxy.example.com",
            port=8080,
            username="proxy-user",
            password="proxy-pass",
            expected_egress_ip="203.0.113.10",
        ),
    )

    downloader = client._build_downloader()

    assert downloader == "fake-downloader"
    assert captured["version"] == "v202602"
    oauth_proxy_config = captured["oauth"]["kwargs"]["proxy_config"]
    ad_manager_proxy_config = captured["ad_manager"]["kwargs"]["proxy_config"]
    assert oauth_proxy_config.proxies == {
        "http": "http://proxy-user:proxy-pass@proxy.example.com:8080",
        "https": "http://proxy-user:proxy-pass@proxy.example.com:8080",
    }
    assert ad_manager_proxy_config.proxies == oauth_proxy_config.proxies
    assert captured["ad_manager"]["kwargs"]["network_code"] == "1234567"
