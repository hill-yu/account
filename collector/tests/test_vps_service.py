from __future__ import annotations

from datetime import date
from decimal import Decimal
import threading

import pytest

from app.adx_report_service import AdxReportRow
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


def test_vps_fetch_service_default_builder_rejects_configured_proxy_until_supported(tmp_path) -> None:
    from app.vps_models import AdxAccountProxy, AdxFetchRun
    from app.vps_service import FetchExecutionError, VpsFetchService

    session_factory = _build_test_session_factory(tmp_path, "proxy-unsupported.db")
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

    service = VpsFetchService(session_factory=session_factory)

    with pytest.raises(FetchExecutionError, match="Configured proxy routes are not yet supported"):
        service.run_fetch(
            account_key="a1",
            report_date=date(2026, 5, 14),
            trigger_source="php_manual",
            request_id="req-proxy",
        )

    with session_factory() as db:
        run = db.query(AdxFetchRun).one()

        assert run.status == "failed"
        assert run.error_message is not None
        assert "Configured proxy routes are not yet supported" in run.error_message


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

    with pytest.raises(FetchExecutionError, match="already running"):
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
