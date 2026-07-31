from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
import hashlib
import json
from types import SimpleNamespace

import pytest

from app.models import BootstrapSettings, CollectorRuntimeConfig, CollectorTask, FetchBatch, RuntimeResult, RuntimeSettings
from app.oauth_validation import OAuthValidationResult
from app.oauth_errors import OAuthFailure
from app.config import SettingsError, load_bootstrap_settings, load_settings
from app.fetcher import AdManagerRestReportFetcher, AdManagerSoapReportFetcher, StubFetcher
from app.egress import EgressChecker
from app.runtime import CollectorRuntime


@dataclass
class FakeControlPlaneClient:
    next_task_result: CollectorTask | None = None
    heartbeats: list[tuple[str, str]] = field(default_factory=list)
    batch_callbacks: list[tuple[int, FetchBatch]] = field(default_factory=list)
    status_callbacks: list[tuple[int, str, str | None]] = field(default_factory=list)
    next_task_calls: int = 0
    credential_acks: list[tuple[int, OAuthValidationResult]] = field(default_factory=list)
    failure_classes: list[tuple[int, str | None]] = field(default_factory=list)

    def heartbeat(self, *, status: str, observed_egress_ip: str) -> None:
        self.heartbeats.append((status, observed_egress_ip))

    def get_next_task(self) -> CollectorTask | None:
        self.next_task_calls += 1
        return self.next_task_result

    def submit_batch(self, task_id: int, batch: FetchBatch) -> None:
        self.batch_callbacks.append((task_id, batch))

    def update_task_status(
        self,
        task_id: int,
        status: str,
        message: str | None = None,
        failure_class: str | None = None,
    ) -> None:
        self.status_callbacks.append((task_id, status, message))
        self.failure_classes.append((task_id, failure_class))

    def acknowledge_oauth_credential(self, *, task_id: int, result: OAuthValidationResult) -> None:
        self.credential_acks.append((task_id, result))


@dataclass
class FakeEgressChecker:
    observed_ip: str
    calls: int = 0

    def get_observed_ip(self) -> str:
        self.calls += 1
        return self.observed_ip


@dataclass
class FakeFetcher:
    batches: list[FetchBatch]
    calls: list[CollectorTask] = field(default_factory=list)

    def fetch(self, task: CollectorTask) -> list[FetchBatch]:
        self.calls.append(task)
        return self.batches


@dataclass
class FakeOAuthValidator:
    result: OAuthValidationResult
    calls: int = 0

    def validate(self) -> OAuthValidationResult:
        self.calls += 1
        return self.result


def test_runtime_validates_staged_credential_and_acks_without_fetching_reports() -> None:
    settings = build_settings()
    task = CollectorTask(
        id=19,
        account_id=7,
        collector_instance_id=3,
        task_type="oauth_credential_validate",
        report_date=date(2026, 7, 29),
        status="in_progress",
    )
    client = FakeControlPlaneClient(next_task_result=task)
    fetcher = FakeFetcher(batches=[])
    validation_result = OAuthValidationResult(
        account_id=7,
        credential_version=2,
        token_fingerprint="fingerprint-v2",
        network_code="network-123",
        network_timezone="America/Los_Angeles",
        granted_scopes="https://www.googleapis.com/auth/admanager",
    )
    validator = FakeOAuthValidator(validation_result)
    runtime = CollectorRuntime(
        settings=settings,
        control_plane_client=client,
        egress_checker=FakeEgressChecker(settings.expected_egress_ip),
        fetcher=fetcher,
        oauth_validator=validator,
    )

    result = runtime.run_once()

    assert result == RuntimeResult(outcome="succeeded", task_id=19)
    assert validator.calls == 1
    assert fetcher.calls == []
    assert client.credential_acks == [(19, validation_result)]
    assert client.status_callbacks == []


def test_runtime_reports_structured_oauth_failure_without_exception_text() -> None:
    settings = build_settings()
    task = CollectorTask(
        id=20,
        account_id=7,
        collector_instance_id=3,
        task_type="report_fetch_hourly",
        report_date=date(2026, 7, 30),
        status="in_progress",
    )

    class FailingFetcher:
        def fetch(self, task):
            raise OAuthFailure(failure_class="oauth_refresh_revoked", retryable=False, http_status=400)

    client = FakeControlPlaneClient(next_task_result=task)
    runtime = CollectorRuntime(
        settings=settings,
        control_plane_client=client,
        egress_checker=FakeEgressChecker(settings.expected_egress_ip),
        fetcher=FailingFetcher(),
    )

    with pytest.raises(OAuthFailure):
        runtime.run_once()

    assert client.status_callbacks == [(20, "failed", None)]
    assert client.failure_classes == [(20, "oauth_refresh_revoked")]


def build_settings() -> RuntimeSettings:
    return RuntimeSettings(
        control_plane_base_url="http://control-plane.test",
        instance_token="instance-token",
        proxy_protocol="http",
        proxy_host="proxy.example.com",
        proxy_port=8080,
        proxy_username="proxy-user",
        proxy_password="proxy-pass",
        expected_egress_ip="203.0.113.10",
        fetch_mode="stub",
        admanager_network_code=None,
        google_oauth_client_id=None,
        google_oauth_client_secret=None,
        google_oauth_refresh_token=None,
    )


class FakeResponse:
    def __init__(self, payload: dict[str, object], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict[str, object]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def post(self, url: str, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self._responses.pop(0)

    def get(self, url: str, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self._responses.pop(0)


def test_runtime_blocks_on_egress_mismatch_before_task_polling() -> None:
    client = FakeControlPlaneClient(
        next_task_result=CollectorTask(
            id=7,
            account_id=3,
            collector_instance_id=2,
            task_type="report_fetch",
            report_date=date(2026, 5, 21),
            status="in_progress",
        )
    )
    runtime = CollectorRuntime(
        settings=build_settings(),
        control_plane_client=client,
        egress_checker=FakeEgressChecker("203.0.113.11"),
        fetcher=FakeFetcher([]),
    )

    result = runtime.run_once()

    assert result.outcome == "blocked"
    assert result.reason == "egress_ip_mismatch"
    assert client.heartbeats == [("blocked", "203.0.113.11")]
    assert client.next_task_calls == 0


def test_runtime_fetches_batches_and_callbacks_success() -> None:
    task = CollectorTask(
        id=7,
        account_id=3,
        collector_instance_id=2,
        task_type="report_fetch",
        report_date=date(2026, 5, 21),
        status="in_progress",
    )
    batches = [
        FetchBatch(batch_key="page-1", row_count=2, payload_hash="hash-1", schema_version="admanager_core_v1"),
        FetchBatch(batch_key="page-2", row_count=1, payload_hash="hash-2", schema_version="admanager_core_v1"),
    ]
    client = FakeControlPlaneClient(next_task_result=task)
    fetcher = FakeFetcher(batches)
    runtime = CollectorRuntime(
        settings=build_settings(),
        control_plane_client=client,
        egress_checker=FakeEgressChecker("203.0.113.10"),
        fetcher=fetcher,
    )

    result = runtime.run_once()

    assert result.outcome == "succeeded"
    assert result.task_id == 7
    assert client.heartbeats == [("ready", "203.0.113.10")]
    assert fetcher.calls == [task]
    assert client.batch_callbacks == [(7, batches[0]), (7, batches[1])]
    assert client.status_callbacks == [(7, "succeeded", "uploaded 2 batches")]


def test_runtime_uploads_single_soap_batch_and_marks_task_succeeded() -> None:
    task = CollectorTask(
        id=11,
        account_id=3,
        collector_instance_id=2,
        task_type="report_fetch",
        report_date=date(2026, 6, 3),
        status="in_progress",
    )
    batch = FetchBatch(
        batch_key="page-1",
        row_count=1,
        payload_hash="soap-hash",
        schema_version="admanager_site_core_v1",
        rows=[
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
        ],
    )
    client = FakeControlPlaneClient(next_task_result=task)
    fetcher = FakeFetcher([batch])
    runtime = CollectorRuntime(
        settings=build_settings(),
        control_plane_client=client,
        egress_checker=FakeEgressChecker("203.0.113.10"),
        fetcher=fetcher,
    )

    result = runtime.run_once()

    assert result.outcome == "succeeded"
    assert client.batch_callbacks == [(11, batch)]
    assert client.status_callbacks == [(11, "succeeded", "uploaded 1 batches")]


def test_load_settings_honors_explicit_empty_mapping() -> None:
    with pytest.raises(SettingsError, match="Missing required environment variable"):
        load_settings({})


def test_load_bootstrap_settings_honors_explicit_empty_mapping() -> None:
    with pytest.raises(SettingsError, match="Missing required environment variable"):
        load_bootstrap_settings({})


def test_load_settings_requires_google_auth_when_admanager_rest_enabled() -> None:
    with pytest.raises(SettingsError, match="GOOGLE_ADMANAGER_NETWORK_CODE"):
        load_settings(
            {
                "CONTROL_PLANE_BASE_URL": "http://control-plane.test",
                "COLLECTOR_INSTANCE_TOKEN": "instance-token",
                "COLLECTOR_PROXY_PROTOCOL": "http",
                "COLLECTOR_PROXY_HOST": "proxy.example.com",
                "COLLECTOR_PROXY_PORT": "8080",
                "COLLECTOR_EXPECTED_EGRESS_IP": "203.0.113.10",
                "COLLECTOR_FETCH_MODE": "admanager_rest",
            }
        )


def test_load_settings_requires_google_auth_when_admanager_soap_enabled() -> None:
    with pytest.raises(SettingsError, match="GOOGLE_ADMANAGER_NETWORK_CODE"):
        load_settings(
            {
                "CONTROL_PLANE_BASE_URL": "http://control-plane.test",
                "COLLECTOR_INSTANCE_TOKEN": "instance-token",
                "COLLECTOR_PROXY_PROTOCOL": "http",
                "COLLECTOR_PROXY_HOST": "proxy.example.com",
                "COLLECTOR_PROXY_PORT": "8080",
                "COLLECTOR_EXPECTED_EGRESS_IP": "203.0.113.10",
                "COLLECTOR_FETCH_MODE": "admanager_soap",
            }
        )


def test_runtime_from_settings_uses_stub_fetcher_by_default() -> None:
    runtime = CollectorRuntime.from_settings(build_settings())

    assert isinstance(runtime.fetcher, StubFetcher)


def test_stub_fetcher_returns_site_fixture_batch() -> None:
    task = CollectorTask(
        id=9,
        account_id=4,
        collector_instance_id=3,
        task_type="report_fetch",
        report_date=date(2026, 5, 22),
        status="in_progress",
    )

    batches = list(StubFetcher().fetch(task))

    assert len(batches) == 1
    assert batches[0].schema_version == "admanager_site_core_v1"
    assert batches[0].row_count == 2
    assert batches[0].rows == [
        {
            "report_date": "2026-05-22",
            "url_id": "stub-url-1",
            "url": "https://stub.example.com/",
            "responses_served": 1200,
            "impressions": 1000,
            "clicks": 12,
            "revenue": "15.500000",
            "ecpm": "15.500000",
        },
        {
            "report_date": "2026-05-22",
            "url_id": "stub-url-2",
            "url": "https://stub.example.com/news",
            "responses_served": 800,
            "impressions": 650,
            "clicks": 7,
            "revenue": "6.500000",
            "ecpm": "10.000000",
        },
    ]


def test_runtime_from_settings_builds_admanager_rest_fetcher() -> None:
    runtime = CollectorRuntime.from_settings(
        RuntimeSettings(
            control_plane_base_url="http://control-plane.test",
            instance_token="instance-token",
            proxy_protocol="http",
            proxy_host="proxy.example.com",
            proxy_port=8080,
            proxy_username="proxy-user",
            proxy_password="proxy-pass",
            expected_egress_ip="203.0.113.10",
            fetch_mode="admanager_rest",
            admanager_network_code="1234567",
            google_oauth_client_id="client-id",
            google_oauth_client_secret="client-secret",
            google_oauth_refresh_token="refresh-token",
        )
    )

    assert isinstance(runtime.fetcher, AdManagerRestReportFetcher)


def test_runtime_from_settings_builds_admanager_soap_fetcher() -> None:
    settings = RuntimeSettings(
        control_plane_base_url="http://control-plane.test",
        instance_token="instance-token",
        proxy_protocol="http",
        proxy_host="proxy.example.com",
        proxy_port=8080,
        proxy_username="proxy-user",
        proxy_password="proxy-pass",
        expected_egress_ip="203.0.113.10",
        fetch_mode="admanager_soap",
        admanager_network_code="1234567",
        google_oauth_client_id="client-id",
        google_oauth_client_secret="client-secret",
        google_oauth_refresh_token="refresh-token",
    )

    runtime = CollectorRuntime.from_settings(settings)

    assert isinstance(runtime.fetcher, AdManagerSoapReportFetcher)


def test_egress_checker_supports_inline_observed_ip() -> None:
    checker = EgressChecker(
        check_url="inline://203.0.113.10",
        proxies={"http": "http://proxy.invalid:8080", "https": "http://proxy.invalid:8080"},
        timeout_seconds=5,
    )

    observed_ip = checker.get_observed_ip()

    assert observed_ip == "203.0.113.10"


def test_admanager_rest_fetcher_converts_each_result_page_to_a_batch() -> None:
    task = CollectorTask(
        id=7,
        account_id=3,
        collector_instance_id=2,
        task_type="report_fetch",
        report_date=date(2026, 5, 21),
        status="in_progress",
    )
    first_page_rows = [
        {
            "dimensionValues": [{"intValue": "2001"}, {"stringValue": "https://example.com/top"}],
            "metricValueGroups": [
                {
                    "primaryValues": [
                        {"intValue": "1000"},
                        {"intValue": "950"},
                        {"intValue": "15"},
                        {"value": "12.345678"},
                        {"value": "12.345678"},
                    ]
                }
            ],
        },
        {
            "dimensionValues": [{"intValue": "2002"}, {"stringValue": "https://example.com/sidebar"}],
            "metricValueGroups": [
                {
                    "primaryValues": [
                        {"intValue": "800"},
                        {"intValue": "760"},
                        {"intValue": "8"},
                        {"value": "4.250000"},
                        {"value": "5.312500"},
                    ]
                }
            ],
        },
    ]
    second_page_rows = [
        {
            "dimensionValues": [{"intValue": "2003"}, {"stringValue": "https://example.com/footer"}],
            "metricValueGroups": [
                {
                    "primaryValues": [
                        {"intValue": "420"},
                        {"intValue": "400"},
                        {"intValue": "4"},
                        {"value": "2.100000"},
                        {"value": "5.000000"},
                    ]
                }
            ],
        }
    ]
    first_page_normalized = [
        {
            "report_date": "2026-05-21",
            "url_id": "2001",
            "url": "https://example.com/top",
            "responses_served": 1000,
            "impressions": 950,
            "clicks": 15,
            "revenue": "12.345678",
            "ecpm": "12.345678",
        },
        {
            "report_date": "2026-05-21",
            "url_id": "2002",
            "url": "https://example.com/sidebar",
            "responses_served": 800,
            "impressions": 760,
            "clicks": 8,
            "revenue": "4.250000",
            "ecpm": "5.312500",
        },
    ]
    second_page_normalized = [
        {
            "report_date": "2026-05-21",
            "url_id": "2003",
            "url": "https://example.com/footer",
            "responses_served": 420,
            "impressions": 400,
            "clicks": 4,
            "revenue": "2.100000",
            "ecpm": "5.000000",
        }
    ]
    session = FakeSession(
        [
            FakeResponse({"access_token": "access-token"}),
            FakeResponse({"name": "networks/1234567/reports/report-1"}),
            FakeResponse({"name": "networks/1234567/operations/reports/runs/op-1", "done": False}),
            FakeResponse(
                {
                    "name": "networks/1234567/operations/reports/runs/op-1",
                    "done": True,
                    "response": {
                        "reportResult": "networks/1234567/reports/report-1/results/result-1",
                    },
                }
            ),
            FakeResponse({"rows": first_page_rows, "nextPageToken": "token-2", "totalRowCount": 3}),
            FakeResponse({"rows": second_page_rows}),
        ]
    )
    fetcher = AdManagerRestReportFetcher(
        network_code="1234567",
        client_id="client-id",
        client_secret="client-secret",
        refresh_token="refresh-token",
        session=session,
        timeout_seconds=12,
        poll_interval_seconds=0,
        page_size=2,
    )

    batches = list(fetcher.fetch(task))

    assert batches == [
        FetchBatch(
            batch_key="page-1",
            row_count=2,
            payload_hash=hashlib.sha256(
                json.dumps(first_page_normalized, separators=(",", ":"), sort_keys=True).encode("utf-8")
            ).hexdigest(),
            schema_version="admanager_site_core_v1",
            rows=first_page_normalized,
        ),
        FetchBatch(
            batch_key="page-2",
            row_count=1,
            payload_hash=hashlib.sha256(
                json.dumps(second_page_normalized, separators=(",", ":"), sort_keys=True).encode("utf-8")
            ).hexdigest(),
            schema_version="admanager_site_core_v1",
            rows=second_page_normalized,
        ),
    ]
    assert session.calls[0] == (
        "POST",
        "https://oauth2.googleapis.com/token",
        {
            "data": {
                "client_id": "client-id",
                "client_secret": "client-secret",
                "refresh_token": "refresh-token",
                "grant_type": "refresh_token",
            },
            "timeout": 12,
        },
    )
    assert session.calls[1] == (
        "POST",
        "https://admanager.googleapis.com/v1/networks/1234567/reports",
        {
            "headers": {"Authorization": "Bearer access-token"},
            "json": {
                "displayName": "collector-task-7-2026-05-21",
                "reportDefinition": {
                    "dimensions": ["URL_ID", "URL"],
                    "metrics": [
                        "AD_SERVER_RESPONSES_SERVED",
                        "AD_SERVER_IMPRESSIONS",
                        "AD_SERVER_CLICKS",
                        "AD_SERVER_REVENUE_WITHOUT_CPD",
                        "AD_SERVER_AVERAGE_ECPM_WITHOUT_CPD",
                    ],
                    "dateRange": {
                        "fixed": {
                            "startDate": {"year": 2026, "month": 5, "day": 21},
                            "endDate": {"year": 2026, "month": 5, "day": 21},
                        }
                    },
                    "reportType": "HISTORICAL",
                },
            },
            "timeout": 12,
        },
    )
    assert session.calls[2] == (
        "POST",
        "https://admanager.googleapis.com/v1/networks/1234567/reports/report-1:run",
        {
            "headers": {"Authorization": "Bearer access-token"},
            "timeout": 12,
        },
    )
    assert session.calls[3] == (
        "GET",
        "https://admanager.googleapis.com/v1/networks/1234567/operations/reports/runs/op-1",
        {
            "headers": {"Authorization": "Bearer access-token"},
            "timeout": 12,
        },
    )
    assert session.calls[4] == (
        "GET",
        "https://admanager.googleapis.com/v1/networks/1234567/reports/report-1/results/result-1:fetchRows",
        {
            "headers": {"Authorization": "Bearer access-token"},
            "params": {"pageSize": 2},
            "timeout": 12,
        },
    )
    assert session.calls[5] == (
        "GET",
        "https://admanager.googleapis.com/v1/networks/1234567/reports/report-1/results/result-1:fetchRows",
        {
            "headers": {"Authorization": "Bearer access-token"},
            "params": {"pageSize": 2, "pageToken": "token-2"},
            "timeout": 12,
        },
    )


def test_main_bootstrap_uses_env_settings_and_runtime_factory(monkeypatch) -> None:
    from app import main as collector_main

    bootstrap_settings = BootstrapSettings(
        control_plane_base_url="http://control-plane.test",
        instance_token="instance-token",
        egress_check_url="https://api.ipify.org",
        request_timeout_seconds=30,
    )
    runtime_config = CollectorRuntimeConfig(
        control_plane_base_url="http://control-plane.test",
        instance_id=2,
        account_id=3,
        expected_egress_ip="203.0.113.10",
        proxy_protocol="http",
        proxy_host="proxy.example.com",
        proxy_port=8080,
        proxy_username="proxy-user",
        proxy_password="proxy-pass",
        egress_check_url="https://api.ipify.org",
        request_timeout_seconds=30,
        google=SimpleNamespace(
            fetch_mode="stub",
            admanager_network_code=None,
            google_oauth_client_id=None,
            google_oauth_client_secret=None,
            google_oauth_refresh_token=None,
        ),
    )
    settings = replace(build_settings(), account_id=3)
    seen: dict[str, object] = {}

    class FakeRuntime:
        def run_once(self) -> SimpleNamespace:
            seen["ran"] = True
            return SimpleNamespace(outcome="succeeded")

    class FakeControlPlaneClient:
        def __init__(self, *, base_url: str, instance_token: str, timeout_seconds: int) -> None:
            seen["client_init"] = {
                "base_url": base_url,
                "instance_token": instance_token,
                "timeout_seconds": timeout_seconds,
            }

        def get_runtime_config(self):
            seen["runtime_config_requested"] = True
            return runtime_config

    def fake_load_bootstrap_settings():
        seen["loaded"] = True
        return bootstrap_settings

    def fake_from_settings(runtime_settings):
        seen["settings"] = runtime_settings
        return FakeRuntime()

    monkeypatch.setattr(collector_main, "load_bootstrap_settings", fake_load_bootstrap_settings)
    monkeypatch.setattr(collector_main, "ControlPlaneClient", FakeControlPlaneClient)
    monkeypatch.setattr(collector_main.CollectorRuntime, "from_settings", fake_from_settings)

    exit_code = collector_main.main()

    assert exit_code == 0
    assert seen == {
        "loaded": True,
        "client_init": {
            "base_url": "http://control-plane.test",
            "instance_token": "instance-token",
            "timeout_seconds": 30,
        },
        "runtime_config_requested": True,
        "settings": settings,
        "ran": True,
    }
