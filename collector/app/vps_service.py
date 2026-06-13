from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Callable, Protocol

from sqlalchemy.orm import Session, sessionmaker

from app.adx_report_service import AdxApiCredentials, AdxReportService
from app.egress import EgressChecker
from app.proxy import ProxyConfig, ProxyConfigError
from app.vps_proxy_resolver import ProxyResolver, ProxyRoute
from app.vps_repository import VpsRepository
from app.vps_models import AdxAccount, AdxFetchRun


class AccountConfigError(ValueError):
    pass


class FetchExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class VpsFetchResult:
    run_id: int
    account_key: str
    report_date: str
    row_count: int
    status: str


@dataclass(frozen=True)
class VpsSiteDailyReportResult:
    account_key: str
    report_date: str
    has_run: bool
    run_status: str | None
    run_id: int | None
    row_count: int
    error_message: str | None
    items: list[dict[str, object]]


ReportServiceFactory = Callable[[AdxAccount, ProxyRoute], AdxReportService | object]


class EgressCheckerProtocol(Protocol):
    def get_observed_ip(self) -> str:
        ...


EgressCheckerFactory = Callable[[ProxyConfig], EgressCheckerProtocol]


class VpsFetchService:
    _active_fetch_keys_guard = threading.Lock()
    _active_fetch_keys: set[tuple[str, date]] = set()

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        report_service_factory: ReportServiceFactory | None = None,
        proxy_resolver: ProxyResolver | None = None,
        egress_checker_factory: EgressCheckerFactory | None = None,
        egress_check_url: str = "https://api.ipify.org",
        request_timeout_seconds: int = 30,
    ) -> None:
        self._session_factory = session_factory
        self._report_service_factory = report_service_factory or self._build_report_service
        self._proxy_resolver = proxy_resolver or ProxyResolver()
        self._egress_checker_factory = egress_checker_factory or self._build_egress_checker
        self._egress_check_url = egress_check_url
        self._request_timeout_seconds = request_timeout_seconds

    def run_fetch(
        self,
        *,
        account_key: str,
        report_date: date,
        trigger_source: str,
        request_id: str,
    ) -> VpsFetchResult:
        lock_key = (account_key, report_date)
        if not self._try_acquire_process_lock(lock_key):
            raise FetchExecutionError(
                "Fetch already executing in this process for "
                f"account_key={account_key} report_date={report_date.isoformat()}"
            )

        try:
            with self._session_factory() as db:
                repo = VpsRepository(db)
                account = repo.get_active_account_by_key(account_key, lock_for_update=True)
                if account is None:
                    raise AccountConfigError(f"Unknown active account_key: {account_key}")

                existing_run = repo.get_active_fetch_run(account_id=account.id, report_date=report_date)
                if existing_run is not None:
                    raise FetchExecutionError(
                        "Fetch already queued or running for "
                        f"account_key={account_key} report_date={report_date.isoformat()} "
                        f"(run_id={existing_run.id}, request_id={existing_run.request_id})"
                    )

                proxy_binding = repo.get_active_proxy_for_account(account.id)
                try:
                    proxy_route = self._proxy_resolver.resolve(account=account, proxy_binding=proxy_binding)
                except ProxyConfigError as exc:
                    raise AccountConfigError(
                        f"Invalid proxy configuration for account_key={account_key}: {exc}"
                    ) from exc
                proxy_config = self._proxy_config_from_route(proxy_route)

                try:
                    run = None
                    run = repo.create_fetch_run(
                        account_id=account.id,
                        report_date=report_date,
                        trigger_source=trigger_source,
                        request_id=request_id,
                    )
                    db.commit()
                    self._verify_proxy_egress(proxy_config)
                    report_service = self._report_service_factory(account, proxy_route)
                    rows = report_service.fetch_site_daily_report(report_date=report_date, task_id=run.id)
                    repo.replace_site_rows(
                        account_id=account.id,
                        report_date=report_date,
                        fetch_run_id=run.id,
                        rows=rows,
                    )
                    repo.mark_run_success(run, row_count=len(rows))
                    db.commit()
                except Exception as exc:
                    db.rollback()
                    if run is not None:
                        repo.mark_run_failed(run, message=str(exc))
                        db.commit()
                    raise FetchExecutionError(str(exc)) from exc

                return VpsFetchResult(
                    run_id=run.id,
                    account_key=account.account_key,
                    report_date=report_date.isoformat(),
                    row_count=len(rows),
                    status="success",
                )
        finally:
            self._release_process_lock(lock_key)

    def enqueue_fetch(
        self,
        *,
        account_key: str,
        report_date: date,
        trigger_source: str,
        request_id: str,
    ) -> VpsFetchResult:
        with self._session_factory() as db:
            repo = VpsRepository(db)
            account = repo.get_active_account_by_key(account_key, lock_for_update=True)
            if account is None:
                raise AccountConfigError(f"Unknown active account_key: {account_key}")

            existing_run = repo.get_active_fetch_run(account_id=account.id, report_date=report_date)
            if existing_run is not None:
                raise FetchExecutionError(
                    "Fetch already queued or running for "
                    f"account_key={account_key} report_date={report_date.isoformat()} "
                    f"(run_id={existing_run.id}, request_id={existing_run.request_id})"
                )

            run = repo.create_fetch_run(
                account_id=account.id,
                report_date=report_date,
                trigger_source=trigger_source,
                request_id=request_id,
            )
            db.commit()

            return VpsFetchResult(
                run_id=run.id,
                account_key=account.account_key,
                report_date=report_date.isoformat(),
                row_count=0,
                status="accepted",
            )

    def get_site_daily_report(
        self,
        *,
        account_key: str,
        report_date: date,
    ) -> VpsSiteDailyReportResult:
        with self._session_factory() as db:
            repo = VpsRepository(db)
            account = repo.get_active_account_by_key(account_key)
            if account is None:
                raise AccountConfigError(f"Unknown active account_key: {account_key}")

            run = repo.get_latest_completed_fetch_run(account_id=account.id, report_date=report_date)
            rows = repo.list_site_rows(account_id=account.id, report_date=report_date)

            return VpsSiteDailyReportResult(
                account_key=account.account_key,
                report_date=report_date.isoformat(),
                has_run=run is not None,
                run_status="success" if run is not None else None,
                run_id=run.id if run is not None else None,
                row_count=len(rows) if run is not None else 0,
                error_message=None,
                items=[_site_row_to_payload(row) for row in rows] if run is not None else [],
            )

    def execute_fetch_run(self, run_id: int) -> VpsFetchResult | None:
        with self._session_factory() as db:
            repo = VpsRepository(db)
            run = repo.claim_fetch_run(run_id=run_id)
            if run is None:
                return None

            account = db.get(AdxAccount, run.account_id)
            report_date = run.report_date
            if account is None:
                repo.mark_run_failed(run, message=f"Missing account for run_id={run.id}")
                db.commit()
                return VpsFetchResult(
                    run_id=run.id,
                    account_key="",
                    report_date=report_date.isoformat(),
                    row_count=0,
                    status="failed",
                )

            proxy_binding = repo.get_active_proxy_for_account(account.id)
            try:
                proxy_route = self._proxy_resolver.resolve(account=account, proxy_binding=proxy_binding)
            except ProxyConfigError as exc:
                repo.mark_run_failed(run, message=str(exc))
                db.commit()
                return VpsFetchResult(
                    run_id=run.id,
                    account_key=account.account_key,
                    report_date=report_date.isoformat(),
                    row_count=0,
                    status="failed",
                )
            proxy_config = self._proxy_config_from_route(proxy_route)

            try:
                self._verify_proxy_egress(proxy_config)
                report_service = self._report_service_factory(account, proxy_route)
                rows = report_service.fetch_site_daily_report(report_date=run.report_date, task_id=run.id)
                repo.replace_site_rows(
                    account_id=account.id,
                    report_date=run.report_date,
                    fetch_run_id=run.id,
                    rows=rows,
                )
                repo.mark_run_success(run, row_count=len(rows))
                db.commit()
                return VpsFetchResult(
                    run_id=run.id,
                    account_key=account.account_key,
                    report_date=report_date.isoformat(),
                    row_count=len(rows),
                    status="success",
                )
            except Exception as exc:
                db.rollback()
                run = db.get(AdxFetchRun, run_id)
                if run is not None:
                    repo.mark_run_failed(run, message=str(exc))
                    db.commit()
                return VpsFetchResult(
                    run_id=run_id,
                    account_key=account.account_key,
                    report_date=report_date.isoformat(),
                    row_count=0,
                    status="failed",
                )

    def process_next_pending_fetch(self) -> VpsFetchResult | None:
        with self._session_factory() as db:
            repo = VpsRepository(db)
            run = repo.get_next_pending_fetch_run()
            if run is None:
                return None
            run_id = run.id

        return self.execute_fetch_run(run_id)

    @staticmethod
    def _build_report_service(account: AdxAccount, proxy_route: ProxyRoute) -> AdxReportService:
        return AdxReportService(
            credentials=AdxApiCredentials(
                network_code=account.network_code,
                client_id=account.client_id,
                client_secret=account.client_secret,
                refresh_token=account.refresh_token,
            ),
            proxy_config=VpsFetchService._proxy_config_from_route(proxy_route),
        )

    @staticmethod
    def _proxy_config_from_route(proxy_route: ProxyRoute) -> ProxyConfig | None:
        if proxy_route.mode == "direct":
            return None
        return ProxyConfig(
            protocol=proxy_route.proxy_type or "",
            host=proxy_route.proxy_host or "",
            port=proxy_route.proxy_port or 0,
            username=proxy_route.proxy_username,
            password=proxy_route.proxy_password,
            expected_egress_ip=proxy_route.expected_egress_ip or "",
        )

    def _build_egress_checker(self, proxy_config: ProxyConfig) -> EgressChecker:
        return EgressChecker(
            check_url=self._egress_check_url,
            proxies=proxy_config.as_requests_proxies(),
            timeout_seconds=self._request_timeout_seconds,
        )

    def _verify_proxy_egress(self, proxy_config: ProxyConfig | None) -> None:
        if proxy_config is None:
            return
        checker = self._egress_checker_factory(proxy_config)
        try:
            observed_ip = checker.get_observed_ip()
        except Exception as exc:
            raise RuntimeError(f"Configured proxy egress check failed: {exc}") from exc
        if observed_ip != proxy_config.expected_egress_ip:
            raise RuntimeError(
                "Configured proxy egress IP mismatch: "
                f"observed {observed_ip} expected {proxy_config.expected_egress_ip}"
            )

    @classmethod
    def _try_acquire_process_lock(cls, lock_key: tuple[str, date]) -> bool:
        with cls._active_fetch_keys_guard:
            if lock_key in cls._active_fetch_keys:
                return False
            cls._active_fetch_keys.add(lock_key)
            return True

    @classmethod
    def _release_process_lock(cls, lock_key: tuple[str, date]) -> None:
        with cls._active_fetch_keys_guard:
            cls._active_fetch_keys.discard(lock_key)


def _site_row_to_payload(row) -> dict[str, object]:
    return {
        "site_name": row.site_name,
        "responses_served": row.responses_served,
        "impressions": row.impressions,
        "clicks": row.clicks,
        "revenue": _format_decimal(row.revenue),
        "ecpm": _format_decimal(row.ecpm),
    }


def _format_decimal(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.000001")), "f")
