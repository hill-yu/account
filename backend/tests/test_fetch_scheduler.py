from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

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


def test_scheduler_uses_previous_pacific_date_for_first_cross_day_finalization(
    session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "cross_day_finalize_account_keys", "coeurdazur")
    monkeypatch.setattr(settings, "direct_collector_only", True)
    monkeypatch.setattr("app.collectors.scheduler.service._launch_hourly_sync_runtime", lambda instance: None)
    account_id, instance_id = _create_account_with_instance(
        session_factory,
        account_name="coeurdazur.com",
        instance_name="coeurdazur-instance",
        report_account_key="coeurdazur",
    )
    with session_factory() as session:
        session.add(
            FetchSchedule(
                account_id=account_id,
                collector_instance_id=instance_id,
                enabled=True,
                mode="interval_hours",
                interval_hours=1,
                timezone="America/Los_Angeles",
                next_run_at=datetime(2026, 8, 11, 8, 21, tzinfo=UTC),
            )
        )
        session.commit()

    captured: dict[str, object] = {}

    def fake_trigger(db: Session, payload, **kwargs):
        captured["report_date"] = payload.report_date
        captured.update(kwargs)
        return collector_schemas.ManualFetchResponse(ok=True, status="pending")

    scheduler = FetchScheduler(
        session_factory=session_factory,
        trigger_manual_fetch=fake_trigger,
        now_provider=lambda: datetime(2026, 8, 11, 8, 21, tzinfo=UTC),
    )

    scheduler.run_pending_once()

    assert captured["report_date"] == date(2026, 8, 10)
    assert captured["run_reason"] == "cross_day_finalize"
    assert captured["external_request_id"] == f"hourly-finalize-{account_id}-2026-08-10-1"


@pytest.mark.parametrize(
    ("attempt_statuses", "expected_date", "expected_reason", "expected_attempt"),
    [
        (["succeeded"], date(2026, 8, 11), "preview", None),
        (["pending"], date(2026, 8, 10), "cross_day_finalize", 1),
        (["blocked"], date(2026, 8, 11), "preview", None),
        (["failed"], date(2026, 8, 10), "cross_day_finalize", 2),
        (["cancelled"], date(2026, 8, 10), "cross_day_finalize", 2),
        (["failed", "failed"], date(2026, 8, 11), "preview", None),
    ],
)
def test_scheduler_cross_day_finalization_is_idempotent_and_bounded(
    session_factory,
    monkeypatch: pytest.MonkeyPatch,
    attempt_statuses: list[str],
    expected_date: date,
    expected_reason: str,
    expected_attempt: int | None,
) -> None:
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "cross_day_finalize_account_keys", "coeurdazur")
    monkeypatch.setattr("app.collectors.scheduler.service._launch_hourly_sync_runtime", lambda instance: None)
    account_id, instance_id = _create_account_with_instance(
        session_factory,
        account_name="bounded-account",
        instance_name="bounded-instance",
        report_account_key="coeurdazur",
    )
    with session_factory() as session:
        session.add(
            FetchSchedule(
                account_id=account_id,
                collector_instance_id=instance_id,
                enabled=True,
                mode="interval_hours",
                interval_hours=1,
                timezone="America/Los_Angeles",
                next_run_at=datetime(2026, 8, 11, 9, 21, tzinfo=UTC),
            )
        )
        for attempt, status_value in enumerate(attempt_statuses, start=1):
            session.add(
                CollectorSyncTask(
                    account_id=account_id,
                    collector_instance_id=instance_id,
                    task_type="report_fetch_hourly",
                    run_reason="cross_day_finalize",
                    report_date=date(2026, 8, 10),
                    status=status_value,
                    external_request_id=f"existing-finalize-{account_id}-{attempt}",
                )
            )
        session.commit()

    captured: dict[str, object] = {}

    def fake_trigger(db: Session, payload, **kwargs):
        captured["report_date"] = payload.report_date
        captured.update(kwargs)
        return collector_schemas.ManualFetchResponse(ok=True, status="pending")

    FetchScheduler(
        session_factory=session_factory,
        trigger_manual_fetch=fake_trigger,
        now_provider=lambda: datetime(2026, 8, 11, 9, 21, tzinfo=UTC),
    ).run_pending_once()

    assert captured["report_date"] == expected_date
    assert captured.get("run_reason", "preview") == expected_reason
    if expected_attempt is None:
        assert captured.get("external_request_id") is None
    else:
        assert captured["external_request_id"] == (
            f"hourly-finalize-{account_id}-2026-08-10-{expected_attempt}"
        )


@pytest.mark.parametrize(
    ("now", "enabled_keys"),
    [
        (datetime(2026, 8, 11, 7, 21, tzinfo=UTC), "coeurdazur"),
        (datetime(2026, 8, 11, 10, 21, tzinfo=UTC), "coeurdazur"),
        (datetime(2026, 8, 11, 8, 21, tzinfo=UTC), ""),
    ],
)
def test_scheduler_does_not_finalize_outside_window_or_feature_scope(
    session_factory,
    monkeypatch: pytest.MonkeyPatch,
    now: datetime,
    enabled_keys: str,
) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "cross_day_finalize_account_keys", enabled_keys)
    monkeypatch.setattr("app.collectors.scheduler.service._launch_hourly_sync_runtime", lambda instance: None)
    account_id, instance_id = _create_account_with_instance(
        session_factory,
        account_name=f"window-account-{now.hour}-{len(enabled_keys)}",
        instance_name=f"window-instance-{now.hour}-{len(enabled_keys)}",
        report_account_key="coeurdazur",
    )
    with session_factory() as session:
        session.add(
            FetchSchedule(
                account_id=account_id,
                collector_instance_id=instance_id,
                enabled=True,
                mode="interval_hours",
                interval_hours=1,
                timezone="America/Los_Angeles",
                next_run_at=now,
            )
        )
        session.commit()

    captured: dict[str, object] = {}

    def fake_trigger(db: Session, payload, **kwargs):
        captured["report_date"] = payload.report_date
        captured.update(kwargs)
        return collector_schemas.ManualFetchResponse(ok=True, status="pending")

    FetchScheduler(
        session_factory=session_factory,
        trigger_manual_fetch=fake_trigger,
        now_provider=lambda: now,
    ).run_pending_once()

    assert captured["report_date"] == now.astimezone(ZoneInfo("America/Los_Angeles")).date()
    assert captured.get("run_reason", "preview") == "preview"
    assert captured.get("external_request_id") is None


def test_scheduler_does_not_finalize_when_direct_collector_mode_is_disabled(
    session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "cross_day_finalize_account_keys", "coeurdazur")
    monkeypatch.setattr(settings, "direct_collector_only", False)
    monkeypatch.setattr("app.collectors.scheduler.service._launch_hourly_sync_runtime", lambda instance: None)
    account_id, instance_id = _create_account_with_instance(
        session_factory,
        account_name="remote-account",
        instance_name="remote-instance",
        report_account_key="coeurdazur",
    )
    now = datetime(2026, 8, 11, 9, 21, tzinfo=UTC)
    with session_factory() as session:
        session.add(
            FetchSchedule(
                account_id=account_id,
                collector_instance_id=instance_id,
                enabled=True,
                mode="interval_hours",
                interval_hours=1,
                timezone="America/Los_Angeles",
                next_run_at=now,
            )
        )
        session.commit()

    captured: dict[str, object] = {}

    def fake_trigger(db: Session, payload, **kwargs):
        captured["report_date"] = payload.report_date
        captured.update(kwargs)
        return collector_schemas.ManualFetchResponse(ok=True, status="pending")

    FetchScheduler(
        session_factory=session_factory,
        trigger_manual_fetch=fake_trigger,
        now_provider=lambda: now,
    ).run_pending_once()

    assert captured["report_date"] == date(2026, 8, 11)
    assert captured.get("run_reason", "preview") == "preview"
    assert captured["direct_collector_only"] is False


def test_scheduler_records_one_exhausted_marker_after_two_failed_attempts(
    session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "cross_day_finalize_account_keys", "coeurdazur")
    monkeypatch.setattr(settings, "direct_collector_only", True)
    monkeypatch.setattr("app.collectors.scheduler.service._launch_hourly_sync_runtime", lambda instance: None)
    account_id, instance_id = _create_account_with_instance(
        session_factory,
        account_name="exhausted-account",
        instance_name="exhausted-instance",
        report_account_key="coeurdazur",
    )
    now = datetime(2026, 8, 11, 9, 21, tzinfo=UTC)
    with session_factory() as session:
        session.add(
            FetchSchedule(
                account_id=account_id,
                collector_instance_id=instance_id,
                enabled=True,
                mode="interval_hours",
                interval_hours=1,
                timezone="America/Los_Angeles",
                next_run_at=now,
            )
        )
        for attempt in (1, 2):
            session.add(
                CollectorSyncTask(
                    account_id=account_id,
                    collector_instance_id=instance_id,
                    task_type="report_fetch_hourly",
                    run_reason="cross_day_finalize",
                    report_date=date(2026, 8, 10),
                    status="failed",
                    external_request_id=f"hourly-finalize-{account_id}-2026-08-10-{attempt}",
                )
            )
        session.commit()

    def fake_trigger(db: Session, payload, **kwargs):
        return collector_schemas.ManualFetchResponse(ok=True, status="pending")

    scheduler = FetchScheduler(
        session_factory=session_factory,
        trigger_manual_fetch=fake_trigger,
        now_provider=lambda: now,
    )
    scheduler.run_pending_once()
    with session_factory() as session:
        schedule = session.query(FetchSchedule).filter_by(account_id=account_id).one()
        schedule.next_run_at = now
        session.commit()
    scheduler.run_pending_once()

    with session_factory() as session:
        markers = list(
            session.scalars(
                select(CollectorSyncTask).where(
                    CollectorSyncTask.account_id == account_id,
                    CollectorSyncTask.report_date == date(2026, 8, 10),
                    CollectorSyncTask.run_reason == "cross_day_finalize_exhausted",
                )
            )
        )
    assert len(markers) == 1
    assert markers[0].status == "blocked"
    assert markers[0].external_request_id == f"hourly-finalize-{account_id}-2026-08-10-exhausted"


def test_scheduler_persists_cross_day_finalize_reason_and_deterministic_request_id(
    session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "cross_day_finalize_account_keys", "coeurdazur")
    monkeypatch.setattr(settings, "direct_collector_only", True)
    monkeypatch.setattr("app.collectors.service._launch_hourly_sync_runtime", lambda instance: None)
    monkeypatch.setattr("app.collectors.scheduler.service._launch_hourly_sync_runtime", lambda instance: None)
    account_id, instance_id = _create_account_with_instance(
        session_factory,
        account_name="persist-account",
        instance_name="persist-instance",
        report_account_key="coeurdazur",
    )
    with session_factory() as session:
        session.add(
            FetchSchedule(
                account_id=account_id,
                collector_instance_id=instance_id,
                enabled=True,
                mode="interval_hours",
                interval_hours=1,
                timezone="America/Los_Angeles",
                next_run_at=datetime(2026, 8, 11, 8, 21, tzinfo=UTC),
            )
        )
        session.commit()

    FetchScheduler(
        session_factory=session_factory,
        now_provider=lambda: datetime(2026, 8, 11, 8, 21, tzinfo=UTC),
    ).run_pending_once()

    with session_factory() as session:
        task = session.scalar(
            select(CollectorSyncTask).where(CollectorSyncTask.run_reason == "cross_day_finalize")
        )
        assert task is not None
        assert task.report_date == date(2026, 8, 10)
        assert task.external_request_id == f"hourly-finalize-{account_id}-2026-08-10-1"


def test_scheduler_cross_day_finalization_uses_zoneinfo_across_dst_fallback(
    session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "cross_day_finalize_account_keys", " coeurdazur , other ")
    monkeypatch.setattr("app.collectors.scheduler.service._launch_hourly_sync_runtime", lambda instance: None)
    account_id, instance_id = _create_account_with_instance(
        session_factory,
        account_name="dst-account",
        instance_name="dst-instance",
        report_account_key="coeurdazur",
    )
    now = datetime(2026, 11, 1, 9, 30, tzinfo=UTC)
    with session_factory() as session:
        session.add(
            FetchSchedule(
                account_id=account_id,
                collector_instance_id=instance_id,
                enabled=True,
                mode="interval_hours",
                interval_hours=1,
                timezone="America/Los_Angeles",
                next_run_at=now,
            )
        )
        session.commit()

    captured: dict[str, object] = {}

    def fake_trigger(db: Session, payload, **kwargs):
        captured["report_date"] = payload.report_date
        captured.update(kwargs)
        return collector_schemas.ManualFetchResponse(ok=True, status="pending")

    FetchScheduler(
        session_factory=session_factory,
        trigger_manual_fetch=fake_trigger,
        now_provider=lambda: now,
    ).run_pending_once()

    assert now.astimezone(ZoneInfo("America/Los_Angeles")).hour == 1
    assert captured["report_date"] == date(2026, 10, 31)
    assert captured["run_reason"] == "cross_day_finalize"


def test_scheduler_cross_day_finalization_uses_source_timezone_when_schedule_timezone_is_wrong(
    session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "cross_day_finalize_account_keys", "coeurdazur")
    monkeypatch.setattr("app.collectors.scheduler.service._launch_hourly_sync_runtime", lambda instance: None)
    account_id, instance_id = _create_account_with_instance(
        session_factory,
        account_name="source-zone-account",
        instance_name="source-zone-instance",
        report_account_key="coeurdazur",
    )
    now = datetime(2026, 8, 11, 8, 21, tzinfo=UTC)
    with session_factory() as session:
        session.add(
            FetchSchedule(
                account_id=account_id,
                collector_instance_id=instance_id,
                enabled=True,
                mode="interval_hours",
                interval_hours=1,
                timezone="Asia/Hong_Kong",
                next_run_at=now,
            )
        )
        session.commit()

    captured: dict[str, object] = {}

    def fake_trigger(db: Session, payload, **kwargs):
        captured["report_date"] = payload.report_date
        captured.update(kwargs)
        return collector_schemas.ManualFetchResponse(ok=True, status="pending")

    FetchScheduler(
        session_factory=session_factory,
        trigger_manual_fetch=fake_trigger,
        now_provider=lambda: now,
    ).run_pending_once()

    assert captured["report_date"] == date(2026, 8, 10)
    assert captured["run_reason"] == "cross_day_finalize"


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


@pytest.mark.parametrize(
    ("report_date", "timezone_name", "expected_ready_at"),
    [
        (date(2026, 8, 4), "Asia/Shanghai", datetime(2026, 8, 4, 21, 0, tzinfo=UTC)),
        (date(2026, 8, 4), "America/Los_Angeles", datetime(2026, 8, 5, 12, 0, tzinfo=UTC)),
        (date(2026, 3, 7), "America/Los_Angeles", datetime(2026, 3, 8, 13, 0, tzinfo=UTC)),
        (date(2026, 10, 31), "America/Los_Angeles", datetime(2026, 11, 1, 12, 0, tzinfo=UTC)),
    ],
)
def test_authoritative_daily_ready_at_waits_five_hours_after_business_day_end(
    report_date: date,
    timezone_name: str,
    expected_ready_at: datetime,
) -> None:
    assert collectors_service.authoritative_daily_ready_at(
        report_date=report_date,
        timezone_name=timezone_name,
    ) == expected_ready_at
    assert not collectors_service.is_authoritative_daily_ready(
        report_date=report_date,
        timezone_name=timezone_name,
        now=expected_ready_at - timedelta(minutes=1),
    )
    assert collectors_service.is_authoritative_daily_ready(
        report_date=report_date,
        timezone_name=timezone_name,
        now=expected_ready_at,
    )


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
