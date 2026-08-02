from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app import models as _models  # noqa: F401
from app.collectors import schemas as collector_schemas
from app.database import Base
from app.main import create_app
from app.models.account import Account
from app.models.account_daily_report import AccountDailyReport
from app.models.collector_instance import CollectorInstance
from app.models.collector_account_policy import CollectorAccountPolicy
from app.models.collector_sync_task import CollectorSyncTask
from app.models.fetch_schedule import FetchSchedule
from app.collectors import service as collectors_service
from app.collectors.scheduler import (
    FetchScheduler,
    compute_daily_times_next_run,
    compute_interval_hours_next_run,
    compute_next_run_at,
)


@pytest.fixture()
def session_factory(tmp_path: Path):
    database_path = tmp_path / "fetch-scheduler.db"
    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session)
    try:
        yield factory
    finally:
        engine.dispose()


def test_daily_times_schedule_picks_next_time_today() -> None:
    now = datetime(2026, 6, 23, 8, 0, tzinfo=UTC)

    actual = compute_daily_times_next_run(
        daily_times=["09:00", "21:00"],
        timezone_name="UTC",
        now=now,
    )

    assert actual == datetime(2026, 6, 23, 9, 0, tzinfo=UTC)


def test_daily_times_schedule_rolls_to_tomorrow_when_all_times_passed() -> None:
    now = datetime(2026, 6, 23, 22, 0, tzinfo=UTC)

    actual = compute_daily_times_next_run(
        daily_times=["09:00", "21:00"],
        timezone_name="UTC",
        now=now,
    )

    assert actual == datetime(2026, 6, 24, 9, 0, tzinfo=UTC)


def test_interval_hours_schedule_uses_last_triggered_at() -> None:
    last_triggered_at = datetime(2026, 6, 23, 1, 30, tzinfo=UTC)

    actual = compute_interval_hours_next_run(
        interval_hours=12,
        last_triggered_at=last_triggered_at,
        now=datetime(2026, 6, 23, 8, 0, tzinfo=UTC),
    )

    assert actual == datetime(2026, 6, 23, 13, 30, tzinfo=UTC)


def test_compute_next_run_at_dispatches_by_mode() -> None:
    now = datetime(2026, 6, 23, 8, 0, tzinfo=UTC)

    daily_result = compute_next_run_at(
        mode="daily_times",
        daily_times=["09:00"],
        interval_hours=None,
        timezone_name="UTC",
        last_triggered_at=None,
        now=now,
    )
    interval_result = compute_next_run_at(
        mode="interval_hours",
        daily_times=None,
        interval_hours=6,
        timezone_name="UTC",
        last_triggered_at=datetime(2026, 6, 23, 2, 0, tzinfo=UTC),
        now=now,
    )

    assert daily_result == datetime(2026, 6, 23, 9, 0, tzinfo=UTC)
    assert interval_result == datetime(2026, 6, 23, 8, 0, tzinfo=UTC)


def test_scheduler_triggers_due_schedule_and_updates_state(
    session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "direct_collector_only", False)
    with session_factory() as session:
        account = Account(name="schedule-account", status="active", external_account_id="ext-1")
        session.add(account)
        session.flush()
        instance = CollectorInstance(
            account_id=account.id,
            name="schedule-instance",
            instance_token="token-schedule",
            status="ready",
            report_base_url="https://node.example.com",
            report_account_key="jwtnx",
            report_token="token-jwtnx",
        )
        session.add(instance)
        session.flush()
        schedule = FetchSchedule(
            account_id=account.id,
            collector_instance_id=instance.id,
            enabled=True,
            mode="daily_times",
            daily_times_json='["09:00","21:00"]',
            interval_hours=None,
            timezone="UTC",
            next_run_at=datetime(2026, 6, 23, 8, 0, tzinfo=UTC),
        )
        session.add(schedule)
        session.commit()

    def fake_trigger_manual_fetch(
        db: Session,
        payload,
        *,
        timeout_seconds: int,
        fetch_kind: str,
        direct_collector_only: bool,
    ):
        assert fetch_kind == "automatic_hourly"
        assert direct_collector_only is False
        return collectors_service.schemas.ManualFetchResponse(
            ok=True,
            status="accepted",
            run_id=12,
            request_id="req-12",
            message="queued",
        )

    monkeypatch.setattr("app.collectors.scheduler.service.trigger_manual_fetch", fake_trigger_manual_fetch)

    scheduler = FetchScheduler(
        session_factory=session_factory,
        timeout_seconds=15,
        now_provider=lambda: datetime(2026, 6, 23, 8, 0, tzinfo=UTC),
    )

    processed = scheduler.run_pending_once()

    assert processed == 1

    with session_factory() as session:
        updated = session.query(FetchSchedule).one()
        assert updated.last_trigger_status == "accepted"
        assert updated.last_trigger_message == "queued"
        assert _as_utc(updated.last_triggered_at) == datetime(2026, 6, 23, 8, 0, tzinfo=UTC)
        assert _as_utc(updated.next_run_at) == datetime(2026, 6, 23, 9, 0, tzinfo=UTC)


def test_create_app_disables_scheduler_by_default() -> None:
    app = create_app()

    assert app.state.scheduler_enabled is False


def test_module_level_asgi_app_disables_scheduler() -> None:
    from app.main import app

    assert app.state.scheduler_enabled is False


def test_scheduler_runner_is_a_separate_importable_entrypoint() -> None:
    from app.scheduler_main import main, run_scheduler

    assert callable(main)
    assert callable(run_scheduler)


def test_scheduler_only_creates_daily_fetch_for_gray_accounts(
    session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gray_account_id, gray_instance_id = _create_account_with_instance(
        session_factory,
        account_name="gray-account",
        instance_name="gray-instance",
        report_account_key="reboroots",
    )
    _create_account_with_instance(
        session_factory,
        account_name="non-gray-account",
        instance_name="non-gray-instance",
        report_account_key="not-in-gray",
        gray_enabled=False,
    )

    monkeypatch.setattr(
        "app.collectors.scheduler.service._launch_hourly_sync_runtime",
        lambda instance: None,
    )

    scheduler = FetchScheduler(
        session_factory=session_factory,
        timeout_seconds=15,
        now_provider=lambda: datetime(2026, 7, 12, 12, 0, tzinfo=UTC),
    )

    scheduler.run_pending_once()

    with session_factory() as session:
        tasks = list(session.scalars(select(CollectorSyncTask).order_by(CollectorSyncTask.id.asc())))

    assert [task.task_type for task in tasks] == ["report_fetch", "report_fetch", "report_fetch"]
    assert {task.account_id for task in tasks} == {gray_account_id}
    assert {task.collector_instance_id for task in tasks} == {gray_instance_id}
    assert [task.report_date for task in tasks] == [date(2026, 7, 9), date(2026, 7, 10), date(2026, 7, 11)]


def test_scheduler_creates_daily_fetch_tasks_for_recent_three_days(
    session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_id, instance_id = _create_account_with_instance(
        session_factory,
        account_name="three-day-account",
        instance_name="three-day-instance",
        report_account_key="reboroots",
    )

    monkeypatch.setattr(
        "app.collectors.scheduler.service._launch_hourly_sync_runtime",
        lambda instance: None,
    )

    scheduler = FetchScheduler(
        session_factory=session_factory,
        timeout_seconds=15,
        now_provider=lambda: datetime(2026, 7, 12, 12, 0, tzinfo=UTC),
    )

    scheduler.run_pending_once()

    with session_factory() as session:
        tasks = list(
            session.scalars(
                select(CollectorSyncTask)
                .where(CollectorSyncTask.account_id == account_id)
                .order_by(CollectorSyncTask.report_date.asc())
            )
        )

    assert [task.task_type for task in tasks] == ["report_fetch", "report_fetch", "report_fetch"]
    assert [task.collector_instance_id for task in tasks] == [instance_id, instance_id, instance_id]
    assert [task.report_date for task in tasks] == [date(2026, 7, 9), date(2026, 7, 10), date(2026, 7, 11)]


def test_scheduler_does_not_treat_derived_daily_rows_as_authoritative_fetches(
    session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_id, _ = _create_account_with_instance(
        session_factory,
        account_name="existing-daily-account",
        instance_name="existing-daily-instance",
        report_account_key="reboroots",
    )
    with session_factory() as session:
        session.add(
            AccountDailyReport(
                account_id=account_id,
                report_date=date(2026, 7, 10),
                responses_served=1,
                requests=1,
                impressions=1,
                clicks=0,
                revenue=0,
                ecpm=0,
            )
        )
        session.commit()

    monkeypatch.setattr(
        "app.collectors.scheduler.service._launch_hourly_sync_runtime",
        lambda instance: None,
    )

    scheduler = FetchScheduler(
        session_factory=session_factory,
        timeout_seconds=15,
        now_provider=lambda: datetime(2026, 7, 12, 12, 0, tzinfo=UTC),
    )

    scheduler.run_pending_once()

    with session_factory() as session:
        tasks = list(
            session.scalars(
                select(CollectorSyncTask)
                .where(CollectorSyncTask.account_id == account_id)
                .order_by(CollectorSyncTask.report_date.asc())
            )
        )

    assert [task.report_date for task in tasks] == [date(2026, 7, 9), date(2026, 7, 10), date(2026, 7, 11)]


def test_scheduler_skips_when_active_daily_fetch_task_exists(
    session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_id, instance_id = _create_account_with_instance(
        session_factory,
        account_name="active-daily-account",
        instance_name="active-daily-instance",
        report_account_key="reboroots",
    )
    with session_factory() as session:
        session.add(
            CollectorSyncTask(
                account_id=account_id,
                collector_instance_id=instance_id,
                task_type="report_fetch",
                report_date=date(2026, 7, 10),
                status="pending",
                external_request_id="existing-report-fetch-2026-07-10",
            )
        )
        session.commit()

    monkeypatch.setattr(
        "app.collectors.scheduler.service._launch_hourly_sync_runtime",
        lambda instance: None,
    )

    scheduler = FetchScheduler(
        session_factory=session_factory,
        timeout_seconds=15,
        now_provider=lambda: datetime(2026, 7, 12, 12, 0, tzinfo=UTC),
    )

    scheduler.run_pending_once()

    with session_factory() as session:
        tasks = list(
            session.scalars(
                select(CollectorSyncTask)
                .where(CollectorSyncTask.account_id == account_id)
                .order_by(CollectorSyncTask.report_date.asc(), CollectorSyncTask.id.asc())
            )
        )

    assert [task.report_date for task in tasks] == [date(2026, 7, 9), date(2026, 7, 10), date(2026, 7, 11)]
    assert len([task for task in tasks if task.report_date == date(2026, 7, 10)]) == 1


def test_scheduler_skips_dates_not_ready_for_authoritative_daily(
    session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_id, _ = _create_account_with_instance(
        session_factory,
        account_name="not-ready-account",
        instance_name="not-ready-instance",
        report_account_key="reboroots",
    )

    monkeypatch.setattr(
        "app.collectors.scheduler.service._launch_hourly_sync_runtime",
        lambda instance: None,
    )

    scheduler = FetchScheduler(
        session_factory=session_factory,
        timeout_seconds=15,
        now_provider=lambda: datetime(2026, 7, 12, 1, 0, tzinfo=UTC),
    )

    scheduler.run_pending_once()

    with session_factory() as session:
        tasks = list(
            session.scalars(
                select(CollectorSyncTask)
                .where(CollectorSyncTask.account_id == account_id)
                .order_by(CollectorSyncTask.report_date.asc())
            )
        )

    assert [task.report_date for task in tasks] == [date(2026, 7, 8), date(2026, 7, 9), date(2026, 7, 10)]


def test_scheduler_skips_accounts_marked_as_do_not_fetch(
    session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_id, _ = _create_account_with_instance(
        session_factory,
        account_name="blocked-account",
        instance_name="blocked-instance",
        report_account_key="arongtala",
        gray_enabled=False,
        exclusion_reason="manual",
    )

    monkeypatch.setattr(
        "app.collectors.scheduler.service._launch_hourly_sync_runtime",
        lambda instance: None,
    )

    scheduler = FetchScheduler(
        session_factory=session_factory,
        timeout_seconds=15,
        now_provider=lambda: datetime(2026, 7, 12, 12, 0, tzinfo=UTC),
    )

    scheduler.run_pending_once()

    with session_factory() as session:
        tasks = list(
            session.scalars(
                select(CollectorSyncTask)
                .where(CollectorSyncTask.account_id == account_id)
                .order_by(CollectorSyncTask.report_date.asc())
            )
        )

    assert tasks == []


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _create_account_with_instance(
    session_factory,
    *,
    account_name: str,
    instance_name: str,
    report_account_key: str,
    gray_enabled: bool = True,
    exclusion_reason: str | None = None,
) -> tuple[int, int]:
    with session_factory() as session:
        account = Account(
            name=account_name,
            status="active",
            external_account_id=f"ext-{account_name}",
        )
        session.add(account)
        session.flush()
        instance = CollectorInstance(
            account_id=account.id,
            name=instance_name,
            instance_token=f"token-{instance_name}",
            status="ready",
            report_base_url="https://node.example.com",
            report_account_key=report_account_key,
            report_token=f"report-token-{instance_name}",
        )
        session.add(instance)
        session.add(
            CollectorAccountPolicy(
                account_id=account.id,
                lifecycle_status="active",
                gray_enabled=gray_enabled and exclusion_reason is None,
                hourly_fetch_enabled=gray_enabled and exclusion_reason is None,
                authoritative_daily_enabled=gray_enabled and exclusion_reason is None,
                manual_fetch_enabled=exclusion_reason is None,
                exclusion_reason=exclusion_reason,
            )
        )
        session.commit()
        return account.id, instance.id
