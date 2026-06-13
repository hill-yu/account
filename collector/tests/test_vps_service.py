from __future__ import annotations

from datetime import date
from decimal import Decimal
import threading

import pytest

from app.adx_report_service import AdxReportRow
from app.proxy import ProxyConfig
from app.vps_database import VpsBase, build_session_factory


class FakeReportService:
    def fetch_site_daily_report(self, *, report_date, task_id=1):
        return [
            AdxReportRow(
                report_date=report_date.isoformat(),
                site_name="jane.ghfkl.com",
                responses_served=34,
                impressions=33,
                clicks=4,
                revenue="7.646800",
                ecpm="231.721203",
            )
        ]


def _build_test_session_factory(tmp_path, database_name: str):
    session_factory = build_session_factory(f"sqlite:///{(tmp_path / database_name).as_posix()}", sql_echo=False)
    VpsBase.metadata.create_all(bind=session_factory.kw["bind"])
    return session_factory


def _seed_active_account(session_factory, *, account_key: str = "a1") -> None:
    from app.vps_models import AdxAccount

    with session_factory() as db:
        db.add(
            AdxAccount(
                account_key=account_key,
                account_name="Account 1",
                network_code="23347208010",
                client_id="client-id",
                client_secret="client-secret",
                refresh_token="refresh-token",
                status="active",
            )
        )
        db.commit()


def _get_account_id(session_factory, *, account_key: str = "a1") -> int:
    from app.vps_models import AdxAccount

    with session_factory() as db:
        return db.query(AdxAccount.id).filter(AdxAccount.account_key == account_key).one()[0]


def test_vps_fetch_service_persists_run_and_rows(tmp_path) -> None:
    from app.vps_service import VpsFetchService

    session_factory = _build_test_session_factory(tmp_path, "svc.db")
    _seed_active_account(session_factory)

    service = VpsFetchService(
        session_factory=session_factory,
        report_service_factory=lambda account, proxy_route: FakeReportService(),
    )

    result = service.run_fetch(
        account_key="a1",
        report_date=date(2026, 5, 14),
        trigger_source="php_manual",
        request_id="req-001",
    )

    assert result.status == "success"
    assert result.row_count == 1

    with session_factory() as db:
        from app.vps_models import AdxFetchRun, AdxSiteDailyReport

        run = db.query(AdxFetchRun).one()
        row = db.query(AdxSiteDailyReport).one()

        assert run.status == "success"
        assert run.request_id == "req-001"
        assert row.site_name == "jane.ghfkl.com"
        assert row.revenue == Decimal("7.646800")
        assert row.ecpm == Decimal("231.721203")


def test_vps_fetch_service_enqueue_fetch_creates_pending_run(tmp_path) -> None:
    from app.vps_service import VpsFetchService

    session_factory = _build_test_session_factory(tmp_path, "enqueue.db")
    _seed_active_account(session_factory)

    service = VpsFetchService(
        session_factory=session_factory,
        report_service_factory=lambda account, proxy_route: FakeReportService(),
    )

    result = service.enqueue_fetch(
        account_key="a1",
        report_date=date(2026, 5, 14),
        trigger_source="php_manual",
        request_id="req-enqueue-1",
    )

    assert result.status == "accepted"
    assert result.row_count == 0

    with session_factory() as db:
        from app.vps_models import AdxFetchRun

        run = db.query(AdxFetchRun).one()
        assert run.status == "pending"
        assert run.request_id == "req-enqueue-1"


def test_vps_fetch_service_returns_site_daily_report_rows(tmp_path) -> None:
    from app.vps_service import VpsFetchService

    session_factory = _build_test_session_factory(tmp_path, "site-report.db")
    _seed_active_account(session_factory)

    service = VpsFetchService(
        session_factory=session_factory,
        report_service_factory=lambda account, proxy_route: FakeReportService(),
    )
    service.run_fetch(
        account_key="a1",
        report_date=date(2026, 5, 14),
        trigger_source="php_manual",
        request_id="req-report-1",
    )

    report = service.get_site_daily_report(account_key="a1", report_date=date(2026, 5, 14))

    assert report.account_key == "a1"
    assert report.report_date == "2026-05-14"
    assert report.row_count == 1
    assert report.run_id is not None
    assert report.items == [
        {
            "site_name": "jane.ghfkl.com",
            "responses_served": 34,
            "impressions": 33,
            "clicks": 4,
            "revenue": "7.646800",
            "ecpm": "231.721203",
        }
    ]


def test_vps_fetch_service_execute_fetch_run_consumes_pending_run(tmp_path) -> None:
    from app.vps_service import VpsFetchService

    session_factory = _build_test_session_factory(tmp_path, "worker.db")
    _seed_active_account(session_factory)
    service = VpsFetchService(
        session_factory=session_factory,
        report_service_factory=lambda account, proxy_route: FakeReportService(),
    )

    accepted = service.enqueue_fetch(
        account_key="a1",
        report_date=date(2026, 5, 14),
        trigger_source="php_manual",
        request_id="req-worker-1",
    )

    result = service.execute_fetch_run(accepted.run_id)

    assert result is not None
    assert result.status == "success"
    assert result.row_count == 1


def test_vps_fetch_service_report_ignores_pending_run_until_success_exists(tmp_path) -> None:
    from app.vps_service import VpsFetchService

    session_factory = _build_test_session_factory(tmp_path, "pending-report.db")
    _seed_active_account(session_factory)
    service = VpsFetchService(
        session_factory=session_factory,
        report_service_factory=lambda account, proxy_route: FakeReportService(),
    )

    service.enqueue_fetch(
        account_key="a1",
        report_date=date(2026, 5, 14),
        trigger_source="php_manual",
        request_id="req-pending-status",
    )

    report = service.get_site_daily_report(account_key="a1", report_date=date(2026, 5, 14))

    assert report.has_run is False
    assert report.run_status is None
    assert report.run_id is None
    assert report.row_count == 0
    assert report.error_message is None
    assert report.items == []


def test_vps_fetch_service_report_exposes_not_started_status(tmp_path) -> None:
    from app.vps_service import VpsFetchService

    session_factory = _build_test_session_factory(tmp_path, "not-started-report.db")
    _seed_active_account(session_factory)
    service = VpsFetchService(
        session_factory=session_factory,
        report_service_factory=lambda account, proxy_route: FakeReportService(),
    )

    report = service.get_site_daily_report(account_key="a1", report_date=date(2026, 5, 14))

    assert report.has_run is False
    assert report.run_status is None
    assert report.run_id is None
    assert report.row_count == 0
    assert report.error_message is None
    assert report.items == []


def test_vps_fetch_service_rejects_overlapping_pending_fetch_for_same_account_and_date(tmp_path) -> None:
    from app.vps_service import FetchExecutionError, VpsFetchService

    session_factory = _build_test_session_factory(tmp_path, "pending-overlap.db")
    _seed_active_account(session_factory)
    service = VpsFetchService(
        session_factory=session_factory,
        report_service_factory=lambda account, proxy_route: FakeReportService(),
    )

    accepted = service.enqueue_fetch(
        account_key="a1",
        report_date=date(2026, 5, 14),
        trigger_source="php_manual",
        request_id="req-pending-1",
    )

    with pytest.raises(FetchExecutionError, match="already queued or running"):
        service.enqueue_fetch(
            account_key="a1",
            report_date=date(2026, 5, 14),
            trigger_source="php_manual",
            request_id="req-pending-2",
        )

    assert accepted.status == "accepted"

    with session_factory() as db:
        from app.vps_models import AdxFetchRun

        runs = db.query(AdxFetchRun).all()
        assert len(runs) == 1
        assert runs[0].request_id == "req-pending-1"
        assert runs[0].status == "pending"


def test_vps_fetch_service_report_returns_latest_successful_snapshot_after_failed_rerun(tmp_path) -> None:
    from app.vps_service import VpsFetchService

    class FailingReportService:
        def fetch_site_daily_report(self, *, report_date, task_id=1):
            raise RuntimeError("upstream failed")

    session_factory = _build_test_session_factory(tmp_path, "failed-rerun.db")
    _seed_active_account(session_factory)

    service = VpsFetchService(
        session_factory=session_factory,
        report_service_factory=lambda account, proxy_route: FakeReportService(),
    )
    first = service.run_fetch(
        account_key="a1",
        report_date=date(2026, 5, 14),
        trigger_source="php_manual",
        request_id="req-success-1",
    )

    rerun_service = VpsFetchService(
        session_factory=session_factory,
        report_service_factory=lambda account, proxy_route: FailingReportService(),
    )
    accepted = rerun_service.enqueue_fetch(
        account_key="a1",
        report_date=date(2026, 5, 14),
        trigger_source="php_manual",
        request_id="req-failed-rerun",
    )
    rerun_result = rerun_service.execute_fetch_run(accepted.run_id)

    report = service.get_site_daily_report(account_key="a1", report_date=date(2026, 5, 14))

    assert first.status == "success"
    assert rerun_result is not None
    assert rerun_result.status == "failed"
    assert report.has_run is True
    assert report.run_status == "success"
    assert report.run_id == first.run_id
    assert report.error_message is None
    assert report.row_count == 1
    assert report.items == [
        {
            "site_name": "jane.ghfkl.com",
            "responses_served": 34,
            "impressions": 33,
            "clicks": 4,
            "revenue": "7.646800",
            "ecpm": "231.721203",
        }
    ]


def test_vps_fetch_service_configured_proxy_validates_egress_before_fetch(tmp_path) -> None:
    from app.vps_models import AdxAccountProxy
    from app.vps_service import VpsFetchService

    session_factory = _build_test_session_factory(tmp_path, "proxy-egress-success.db")
    _seed_active_account(session_factory)
    account_id = _get_account_id(session_factory)

    with session_factory() as db:
        db.add(
            AdxAccountProxy(
                account_id=account_id,
                proxy_type="http",
                proxy_host="proxy.example.com",
                proxy_port=8080,
                proxy_username="proxy-user",
                proxy_password="proxy-pass",
                expected_egress_ip="203.0.113.10",
                is_active=True,
            )
        )
        db.commit()

    seen: dict[str, object] = {}

    class FakeEgressChecker:
        def get_observed_ip(self) -> str:
            seen["egress_checked"] = True
            return "203.0.113.10"

    def fake_egress_checker_factory(proxy_config: ProxyConfig):
        seen["proxy_config"] = proxy_config
        return FakeEgressChecker()

    def fake_report_service_factory(account, proxy_route):
        seen["proxy_route"] = proxy_route
        return FakeReportService()

    service = VpsFetchService(
        session_factory=session_factory,
        report_service_factory=fake_report_service_factory,
        egress_checker_factory=fake_egress_checker_factory,
    )

    result = service.run_fetch(
        account_key="a1",
        report_date=date(2026, 5, 14),
        trigger_source="php_manual",
        request_id="req-proxy-success",
    )

    assert result.status == "success"
    assert isinstance(seen["proxy_config"], ProxyConfig)
    assert seen["proxy_config"].as_requests_proxies()["http"] == "http://proxy-user:proxy-pass@proxy.example.com:8080"
    assert seen["egress_checked"] is True
    assert seen["proxy_route"].mode == "configured_proxy"


def test_vps_fetch_service_marks_run_failed_when_proxy_egress_ip_mismatches(tmp_path) -> None:
    from app.vps_models import AdxAccountProxy, AdxFetchRun
    from app.vps_service import FetchExecutionError, VpsFetchService

    session_factory = _build_test_session_factory(tmp_path, "proxy-egress-failed.db")
    _seed_active_account(session_factory)
    account_id = _get_account_id(session_factory)

    with session_factory() as db:
        db.add(
            AdxAccountProxy(
                account_id=account_id,
                proxy_type="http",
                proxy_host="proxy.example.com",
                proxy_port=8080,
                proxy_username="proxy-user",
                proxy_password="proxy-pass",
                expected_egress_ip="203.0.113.10",
                is_active=True,
            )
        )
        db.commit()

    class FakeEgressChecker:
        def get_observed_ip(self) -> str:
            return "203.0.113.99"

    service = VpsFetchService(
        session_factory=session_factory,
        report_service_factory=lambda account, proxy_route: FakeReportService(),
        egress_checker_factory=lambda proxy_config: FakeEgressChecker(),
    )

    with pytest.raises(FetchExecutionError, match="egress IP mismatch"):
        service.run_fetch(
            account_key="a1",
            report_date=date(2026, 5, 14),
            trigger_source="php_manual",
            request_id="req-proxy-mismatch",
        )

    with session_factory() as db:
        run = db.query(AdxFetchRun).one()
        assert run.status == "failed"
        assert run.error_message is not None
        assert "egress IP mismatch" in run.error_message


def test_vps_fetch_service_replaces_existing_rows_for_same_account_and_date(tmp_path) -> None:
    from app.vps_models import AdxSiteDailyReport
    from app.vps_service import VpsFetchService

    class FakeReportServiceTwo:
        def fetch_site_daily_report(self, *, report_date, task_id=1):
            return [
                AdxReportRow(
                    report_date=report_date.isoformat(),
                    site_name="jane.ghfkl.com",
                    responses_served=99,
                    impressions=88,
                    clicks=7,
                    revenue="9.000000",
                    ecpm="102.272727",
                )
            ]

    session_factory = _build_test_session_factory(tmp_path, "rerun.db")
    _seed_active_account(session_factory)

    service = VpsFetchService(
        session_factory=session_factory,
        report_service_factory=lambda account, proxy_route: FakeReportService(),
    )
    service.run_fetch(
        account_key="a1",
        report_date=date(2026, 5, 14),
        trigger_source="php_manual",
        request_id="req-1",
    )

    service_two = VpsFetchService(
        session_factory=session_factory,
        report_service_factory=lambda account, proxy_route: FakeReportServiceTwo(),
    )
    service_two.run_fetch(
        account_key="a1",
        report_date=date(2026, 5, 14),
        trigger_source="php_manual",
        request_id="req-2",
    )

    with session_factory() as db:
        rows = db.query(AdxSiteDailyReport).all()

        assert len(rows) == 1
        assert rows[0].responses_served == 99


def test_vps_fetch_service_default_builder_supports_configured_proxy_routes(tmp_path) -> None:
    from app.vps_models import AdxAccountProxy
    from app.vps_service import VpsFetchService

    session_factory = _build_test_session_factory(tmp_path, "proxy-supported.db")
    _seed_active_account(session_factory)
    account_id = _get_account_id(session_factory)

    with session_factory() as db:
        db.add(
            AdxAccountProxy(
                account_id=account_id,
                proxy_type="http",
                proxy_host="proxy.example.com",
                proxy_port=8080,
                proxy_username="proxy-user",
                proxy_password="proxy-pass",
                expected_egress_ip="203.0.113.10",
                is_active=True,
            )
        )
        db.commit()

    class FakeEgressChecker:
        def get_observed_ip(self) -> str:
            return "203.0.113.10"

    seen: dict[str, object] = {}

    def fake_report_service_factory(account, proxy_route):
        seen["proxy_route"] = proxy_route
        return FakeReportService()

    service = VpsFetchService(
        session_factory=session_factory,
        report_service_factory=fake_report_service_factory,
        egress_checker_factory=lambda proxy_config: FakeEgressChecker(),
    )

    result = service.run_fetch(
        account_key="a1",
        report_date=date(2026, 5, 14),
        trigger_source="php_manual",
        request_id="req-proxy",
    )

    assert result.status == "success"
    assert seen["proxy_route"].mode == "configured_proxy"


def test_vps_fetch_service_rejects_overlapping_running_fetch_for_same_account_and_date(tmp_path) -> None:
    from app.vps_models import AdxFetchRun
    from app.vps_service import FetchExecutionError, VpsFetchService

    session_factory = _build_test_session_factory(tmp_path, "overlap.db")
    _seed_active_account(session_factory)
    account_id = _get_account_id(session_factory)

    with session_factory() as db:
        db.add(
            AdxFetchRun(
                account_id=account_id,
                report_date=date(2026, 5, 14),
                trigger_source="php_manual",
                request_id="req-running",
                status="running",
                row_count=0,
            )
        )
        db.commit()

    service = VpsFetchService(
        session_factory=session_factory,
        report_service_factory=lambda account, proxy_route: FakeReportService(),
    )

    with pytest.raises(FetchExecutionError, match="already queued or running"):
        service.run_fetch(
            account_key="a1",
            report_date=date(2026, 5, 14),
            trigger_source="php_manual",
            request_id="req-overlap",
        )

    with session_factory() as db:
        runs = db.query(AdxFetchRun).all()

        assert len(runs) == 1
        assert runs[0].request_id == "req-running"
        assert runs[0].status == "running"


def test_vps_fetch_service_rejects_invalid_proxy_binding_cleanly(tmp_path) -> None:
    from app.vps_models import AdxAccountProxy, AdxFetchRun
    from app.vps_service import AccountConfigError, VpsFetchService

    session_factory = _build_test_session_factory(tmp_path, "proxy-invalid.db")
    _seed_active_account(session_factory)
    account_id = _get_account_id(session_factory)

    with session_factory() as db:
        db.add(
            AdxAccountProxy(
                account_id=account_id,
                proxy_type="http",
                proxy_host="proxy.example.com",
                proxy_port=8080,
                proxy_username="proxy-user",
                proxy_password=None,
                expected_egress_ip="203.0.113.10",
                is_active=True,
            )
        )
        db.commit()

    service = VpsFetchService(session_factory=session_factory)

    with pytest.raises(AccountConfigError, match="proxy auth requires both username and password"):
        service.run_fetch(
            account_key="a1",
            report_date=date(2026, 5, 14),
            trigger_source="php_manual",
            request_id="req-invalid-proxy",
        )

    with session_factory() as db:
        assert db.query(AdxFetchRun).count() == 0


def test_vps_fetch_service_rejects_same_process_concurrent_fetch_for_same_account_and_date(tmp_path) -> None:
    from app.vps_models import AdxFetchRun
    from app.vps_service import FetchExecutionError, VpsFetchService

    class BlockingFakeReportService:
        def __init__(self, started: threading.Event, release: threading.Event) -> None:
            self._started = started
            self._release = release

        def fetch_site_daily_report(self, *, report_date, task_id=1):
            self._started.set()
            self._release.wait(timeout=5)
            return [
                AdxReportRow(
                    report_date=report_date.isoformat(),
                    site_name="jane.ghfkl.com",
                    responses_served=34,
                    impressions=33,
                    clicks=4,
                    revenue="7.646800",
                    ecpm="231.721203",
                )
            ]

    session_factory = _build_test_session_factory(tmp_path, "same-process-lock.db")
    _seed_active_account(session_factory)
    started = threading.Event()
    release = threading.Event()
    blocking_service = BlockingFakeReportService(started, release)
    service = VpsFetchService(
        session_factory=session_factory,
        report_service_factory=lambda account, proxy_route: blocking_service,
    )

    result_holder: dict[str, object] = {}
    error_holder: dict[str, BaseException] = {}

    def run_first_fetch() -> None:
        try:
            result_holder["result"] = service.run_fetch(
                account_key="a1",
                report_date=date(2026, 5, 14),
                trigger_source="php_manual",
                request_id="req-thread-1",
            )
        except BaseException as exc:  # pragma: no cover - defensive capture for thread failure visibility
            error_holder["error"] = exc

    thread = threading.Thread(target=run_first_fetch)
    thread.start()

    assert started.wait(timeout=5), "first fetch did not start in time"

    with pytest.raises(FetchExecutionError, match="already executing in this process"):
        service.run_fetch(
            account_key="a1",
            report_date=date(2026, 5, 14),
            trigger_source="php_manual",
            request_id="req-thread-2",
        )

    release.set()
    thread.join(timeout=5)

    assert not thread.is_alive(), "first fetch thread did not finish"
    assert "error" not in error_holder
    assert result_holder["result"].status == "success"

    with session_factory() as db:
        runs = db.query(AdxFetchRun).all()

        assert len(runs) == 1
        assert runs[0].request_id == "req-thread-1"
        assert runs[0].status == "success"


def test_vps_repository_can_lock_active_account_lookup() -> None:
    from app.vps_repository import VpsRepository

    class FakeQuery:
        def __init__(self) -> None:
            self.with_for_update_called = False

        def filter(self, *conditions):
            return self

        def with_for_update(self):
            self.with_for_update_called = True
            return self

        def one_or_none(self):
            return "account-row"

    class FakeSession:
        def __init__(self) -> None:
            self.query_instance = FakeQuery()

        def query(self, model):
            return self.query_instance

    fake_session = FakeSession()
    repo = VpsRepository(fake_session)

    result = repo.get_active_account_by_key("a1", lock_for_update=True)

    assert result == "account-row"
    assert fake_session.query_instance.with_for_update_called is True
