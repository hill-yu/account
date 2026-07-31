from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.collectors import service
from app.collectors.scheduler import FetchScheduler
from app.database import Base
from app.models import (
    Account,
    AccountHourlyReport,
    AccountReportDayStatus,
    CollectorAccountPolicy,
    CollectorInstance,
    CollectorSyncTask,
    OAuthAppConfig,
    OAuthEvent,
)


@pytest.fixture()
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'recovery-gap.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


def _seed_recovery_account(
    db: Session,
    *,
    name: str,
    hourly_enabled: bool = True,
    daily_enabled: bool = True,
) -> tuple[Account, CollectorInstance]:
    account = Account(name=f"{name}.com", status="active", timezone="UTC")
    db.add(account)
    db.flush()
    instance = CollectorInstance(
        account_id=account.id,
        name=name,
        instance_token=f"instance-{name}",
        status="active",
        report_account_key=name,
    )
    oauth_app = OAuthAppConfig(
        account_id=account.id,
        client_id=f"client-{name}",
        client_secret="",
        redirect_uri=f"https://{name}.com/oauth/google/callback",
        scopes="https://www.googleapis.com/auth/admanager",
        authorization_status="authorized",
        flow_status="completed",
        runtime_status="healthy",
        active_credential_version=1,
    )
    db.add_all(
        [
            instance,
            oauth_app,
            CollectorAccountPolicy(
                account_id=account.id,
                lifecycle_status="active",
                gray_enabled=True,
                hourly_fetch_enabled=hourly_enabled,
                authoritative_daily_enabled=daily_enabled,
                manual_fetch_enabled=True,
            ),
        ]
    )
    db.flush()
    db.add(
        OAuthEvent(
            account_id=account.id,
            oauth_app_id=oauth_app.id,
            event_type="oauth_gap_scan_requested",
            credential_version=1,
        )
    )
    db.commit()
    return account, instance


def _mark_complete(db: Session, account_id: int, report_date: date) -> None:
    db.add(
        AccountReportDayStatus(
            account_id=account_id,
            report_date=report_date,
            source_timezone="UTC",
            hours_present_json=str(list(range(24))),
            expected_hour_count=24,
            is_complete_day=True,
            is_finalized=True,
        )
    )


def _mark_authoritative_success(
    db: Session,
    account_id: int,
    instance_id: int,
    report_date: date,
) -> None:
    db.add(
        CollectorSyncTask(
            account_id=account_id,
            collector_instance_id=instance_id,
            task_type="report_fetch",
            run_reason="automatic",
            report_date=report_date,
            status="succeeded",
            external_request_id=f"daily-success-{account_id}-{report_date.isoformat()}",
        )
    )


def _mark_current_watermark(db: Session, account_id: int, report_time_utc: datetime) -> None:
    db.add(
        AccountHourlyReport(
            account_id=account_id,
            report_date=report_time_utc.date(),
            hour=report_time_utc.hour,
            report_time_utc=report_time_utc,
            source_timezone="UTC",
        )
    )


def test_complete_hourly_and_authoritative_dates_create_no_recovery_gap(session_factory) -> None:
    now = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
    with session_factory() as db:
        account, instance = _seed_recovery_account(db, name="complete")
        for report_date in (date(2026, 7, 28), date(2026, 7, 29), date(2026, 7, 30)):
            _mark_complete(db, account.id, report_date)
            _mark_authoritative_success(db, account.id, instance.id, report_date)
        _mark_current_watermark(db, account.id, datetime(2026, 7, 31, 11, 0, tzinfo=UTC))
        db.commit()

        gaps = service.scan_oauth_recovery_gaps(db, now=now, lookback_days=3)
        task = service.enqueue_next_oauth_recovery_gap(db, now=now, lookback_days=3)

        assert gaps == []
        assert task is None


def test_missing_hourly_gap_is_prioritized_before_mature_authoritative_daily(session_factory) -> None:
    now = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
    with session_factory() as db:
        account, instance = _seed_recovery_account(db, name="priority")
        _mark_complete(db, account.id, date(2026, 7, 28))
        _mark_complete(db, account.id, date(2026, 7, 30))
        _mark_authoritative_success(db, account.id, instance.id, date(2026, 7, 29))
        _mark_authoritative_success(db, account.id, instance.id, date(2026, 7, 30))
        _mark_current_watermark(db, account.id, datetime(2026, 7, 31, 11, 0, tzinfo=UTC))
        db.commit()

        gaps = service.scan_oauth_recovery_gaps(db, now=now, lookback_days=3)

        assert [(gap.task_type, gap.report_date) for gap in gaps[:2]] == [
            ("report_fetch_hourly", date(2026, 7, 29)),
            ("report_fetch", date(2026, 7, 28)),
        ]


def test_failed_recovery_gap_is_not_automatically_retried(session_factory) -> None:
    now = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
    with session_factory() as db:
        account, instance = _seed_recovery_account(db, name="failed-once", daily_enabled=False)
        db.add(
            CollectorSyncTask(
                account_id=account.id,
                collector_instance_id=instance.id,
                task_type="report_fetch_hourly",
                run_reason="oauth_recovery",
                report_date=date(2026, 7, 28),
                status="failed",
                external_request_id=f"oauth-recovery-hourly-{account.id}-2026-07-28",
            )
        )
        for report_date in (date(2026, 7, 29), date(2026, 7, 30)):
            _mark_complete(db, account.id, report_date)
        _mark_current_watermark(db, account.id, datetime(2026, 7, 31, 11, 0, tzinfo=UTC))
        db.commit()

        assert service.scan_oauth_recovery_gaps(db, now=now, lookback_days=3) == []
        assert service.enqueue_next_oauth_recovery_gap(db, now=now, lookback_days=3) is None


def test_scheduler_enqueues_and_launches_only_one_recovery_account_at_a_time(
    session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
    with session_factory() as db:
        first, first_instance = _seed_recovery_account(db, name="first", daily_enabled=False)
        second, second_instance = _seed_recovery_account(db, name="second", daily_enabled=False)
        for account in (first, second):
            for report_date in (date(2026, 7, 29), date(2026, 7, 30)):
                _mark_complete(db, account.id, report_date)
            _mark_current_watermark(db, account.id, datetime(2026, 7, 31, 11, 0, tzinfo=UTC))
        db.commit()

    launched: list[int] = []

    def assert_committed_before_launch(instance: CollectorInstance) -> None:
        with session_factory() as observer:
            visible_task_count = observer.query(CollectorSyncTask).filter_by(
                collector_instance_id=instance.id,
                run_reason="oauth_recovery",
                status="pending",
            ).count()
        assert visible_task_count == 1
        launched.append(instance.id)

    monkeypatch.setattr(
        "app.collectors.scheduler.service._launch_hourly_sync_runtime",
        assert_committed_before_launch,
    )
    scheduler = FetchScheduler(session_factory=session_factory, now_provider=lambda: now)

    assert scheduler.run_pending_once() == 1
    assert scheduler.run_pending_once() == 0
    with session_factory() as db:
        tasks = list(
            db.scalars(
                select(CollectorSyncTask)
                .where(CollectorSyncTask.run_reason == "oauth_recovery")
                .order_by(CollectorSyncTask.id)
            )
        )
        assert len(tasks) == 1
        assert tasks[0].account_id == first.id
        tasks[0].status = "succeeded"
        db.commit()

    assert scheduler.run_pending_once() == 1
    with session_factory() as db:
        tasks = list(
            db.scalars(
                select(CollectorSyncTask)
                .where(CollectorSyncTask.run_reason == "oauth_recovery")
                .order_by(CollectorSyncTask.id)
            )
        )
        assert [task.account_id for task in tasks] == [first.id, second.id]
    assert launched == [first_instance.id, second_instance.id]
