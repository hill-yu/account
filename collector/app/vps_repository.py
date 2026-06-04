from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.adx_report_service import AdxReportRow
from app.vps_models import AdxAccount, AdxAccountProxy, AdxFetchRun, AdxSiteDailyReport


class VpsRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_active_account_by_key(self, account_key: str, *, lock_for_update: bool = False) -> AdxAccount | None:
        query = self._db.query(AdxAccount).filter(
            AdxAccount.account_key == account_key,
            AdxAccount.status == "active",
        )
        if lock_for_update:
            query = query.with_for_update()
        return query.one_or_none()

    def get_active_proxy_for_account(self, account_id: int) -> AdxAccountProxy | None:
        return (
            self._db.query(AdxAccountProxy)
            .filter(AdxAccountProxy.account_id == account_id, AdxAccountProxy.is_active.is_(True))
            .one_or_none()
        )

    def create_fetch_run(
        self,
        *,
        account_id: int,
        report_date: date,
        trigger_source: str,
        request_id: str,
    ) -> AdxFetchRun:
        run = AdxFetchRun(
            account_id=account_id,
            report_date=report_date,
            trigger_source=trigger_source,
            request_id=request_id,
            status="running",
            row_count=0,
        )
        self._db.add(run)
        self._db.flush()
        return run

    def get_running_fetch_run(self, *, account_id: int, report_date: date) -> AdxFetchRun | None:
        return (
            self._db.query(AdxFetchRun)
            .filter(
                AdxFetchRun.account_id == account_id,
                AdxFetchRun.report_date == report_date,
                AdxFetchRun.status == "running",
            )
            .order_by(AdxFetchRun.id.desc())
            .first()
        )

    def replace_site_rows(
        self,
        *,
        account_id: int,
        report_date: date,
        fetch_run_id: int,
        rows: list[AdxReportRow],
    ) -> None:
        (
            self._db.query(AdxSiteDailyReport)
            .filter(
                AdxSiteDailyReport.account_id == account_id,
                AdxSiteDailyReport.report_date == report_date,
            )
            .delete(synchronize_session=False)
        )
        for row in rows:
            self._db.add(
                AdxSiteDailyReport(
                    account_id=account_id,
                    report_date=report_date,
                    site_name=row.site_name,
                    responses_served=row.responses_served,
                    impressions=row.impressions,
                    clicks=row.clicks,
                    revenue=Decimal(row.revenue),
                    ecpm=Decimal(row.ecpm),
                    fetch_run_id=fetch_run_id,
                )
            )

    def mark_run_success(self, run: AdxFetchRun, *, row_count: int) -> None:
        run.status = "success"
        run.row_count = row_count
        run.error_message = None
        run.finished_at = datetime.now(UTC)

    def mark_run_failed(self, run: AdxFetchRun, *, message: str) -> None:
        run.status = "failed"
        run.error_message = message
        run.finished_at = datetime.now(UTC)
