from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import date
from typing import Callable

from sqlalchemy.orm import Session, sessionmaker

from app.adx_report_service import AdxApiCredentials, AdxReportService
from app.proxy import ProxyConfigError
from app.vps_proxy_resolver import ProxyResolver, ProxyRoute
from app.vps_repository import VpsRepository
from app.vps_models import AdxAccount


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


ReportServiceFactory = Callable[[AdxAccount, ProxyRoute], AdxReportService | object]


class VpsFetchService:
    _active_fetch_keys_guard = threading.Lock()
    _active_fetch_keys: set[tuple[str, date]] = set()

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        report_service_factory: ReportServiceFactory | None = None,
        proxy_resolver: ProxyResolver | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._report_service_factory = report_service_factory or self._build_report_service
        self._proxy_resolver = proxy_resolver or ProxyResolver()

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

                existing_run = repo.get_running_fetch_run(account_id=account.id, report_date=report_date)
                if existing_run is not None:
                    raise FetchExecutionError(
                        "Fetch already running for "
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

                try:
                    run = None
                    run = repo.create_fetch_run(
                        account_id=account.id,
                        report_date=report_date,
                        trigger_source=trigger_source,
                        request_id=request_id,
                    )
                    db.commit()
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

    @staticmethod
    def _build_report_service(account: AdxAccount, proxy_route: ProxyRoute) -> AdxReportService:
        if proxy_route.mode != "direct":
            raise RuntimeError(
                "Configured proxy routes are not yet supported by the default AdxReportService builder"
            )
        return AdxReportService(
            credentials=AdxApiCredentials(
                network_code=account.network_code,
                client_id=account.client_id,
                client_secret=account.client_secret,
                refresh_token=account.refresh_token,
            )
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
