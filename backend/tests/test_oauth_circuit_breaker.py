from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app import models as _models  # noqa: F401
from app.collectors import schemas, service
from app.database import Base
from app.models.account import Account
from app.models.collector_account_policy import CollectorAccountPolicy
from app.models.collector_instance import CollectorInstance
from app.models.collector_sync_task import CollectorSyncTask
from app.models.fetch_schedule import FetchSchedule
from app.models.oauth_app_config import OAuthAppConfig
from app.models.oauth_credential import OAuthCredential
from app.models.oauth_event import OAuthEvent


def _session(tmp_path: Path) -> Session:
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'circuit.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, class_=Session)()


def _seed_account(db: Session, *, runtime_status: str = "healthy", excluded: bool = False):
    account = Account(name="circuit.example", status="active", external_account_id="network-1")
    db.add(account)
    db.flush()
    instance = CollectorInstance(
        account_id=account.id,
        name="circuit-node",
        instance_token="circuit-token",
        status="ready",
    )
    oauth_app = OAuthAppConfig(
        account_id=account.id,
        client_id="client-id",
        client_secret="",
        redirect_uri="https://example.invalid/callback",
        scopes="https://www.googleapis.com/auth/admanager",
        authorization_status="authorized",
        flow_status="completed",
        runtime_status=runtime_status,
        active_credential_version=1,
    )
    policy = CollectorAccountPolicy(
        account_id=account.id,
        lifecycle_status="active",
        gray_enabled=not excluded,
        hourly_fetch_enabled=not excluded,
        authoritative_daily_enabled=not excluded,
        manual_fetch_enabled=True,
        exclusion_reason="invalid_grant" if excluded else None,
        resume_gray_enabled=True if excluded else None,
        resume_hourly_fetch_enabled=True if excluded else None,
        resume_authoritative_daily_enabled=True if excluded else None,
    )
    db.add_all([instance, oauth_app, policy])
    db.flush()
    credential = OAuthCredential(
        oauth_app_id=oauth_app.id,
        version=1,
        status="active",
        client_secret_ciphertext="cipher-client",
        refresh_token_ciphertext="cipher-refresh",
        token_fingerprint="fingerprint-1",
    )
    schedule = FetchSchedule(
        account_id=account.id,
        collector_instance_id=instance.id,
        enabled=not excluded,
        mode="interval_hours",
        interval_hours=4,
        timezone="America/Los_Angeles",
        next_run_at=datetime(2026, 7, 31, 4, 0, tzinfo=UTC) if not excluded else None,
    )
    db.add_all([credential, schedule])
    db.commit()
    return account, instance, oauth_app, policy, schedule


def test_refresh_revoked_revalidates_once_then_opens_circuit(tmp_path: Path) -> None:
    db = _session(tmp_path)
    account, instance, oauth_app, policy, schedule = _seed_account(db)
    failed_task = CollectorSyncTask(
        account_id=account.id,
        collector_instance_id=instance.id,
        task_type="report_fetch_hourly",
        report_date=date(2026, 7, 30),
        status="in_progress",
        external_request_id="failed-hourly",
    )
    queued_task = CollectorSyncTask(
        account_id=account.id,
        collector_instance_id=instance.id,
        task_type="report_fetch",
        report_date=date(2026, 7, 29),
        status="pending",
        external_request_id="queued-daily",
    )
    db.add_all([failed_task, queued_task])
    db.commit()

    service.update_task_status(
        db,
        instance,
        failed_task.id,
        schemas.TaskStatusUpdate(status="failed", failure_class="oauth_refresh_revoked"),
    )

    db.refresh(oauth_app)
    db.refresh(schedule)
    assert oauth_app.runtime_status == "degraded"
    assert oauth_app.failure_count == 1
    assert schedule.enabled is True
    health_task = db.scalar(select(CollectorSyncTask).where(CollectorSyncTask.task_type == "oauth_health_check"))
    assert health_task is not None
    assert health_task.status == "pending"

    health_task.status = "in_progress"
    db.commit()
    service.update_task_status(
        db,
        instance,
        health_task.id,
        schemas.TaskStatusUpdate(status="failed", failure_class="oauth_refresh_revoked", credential_version=1),
    )

    db.refresh(oauth_app)
    db.refresh(policy)
    db.refresh(schedule)
    db.refresh(queued_task)
    assert oauth_app.runtime_status == "revoked"
    assert policy.exclusion_reason == "invalid_grant"
    assert policy.resume_gray_enabled is True
    assert policy.gray_enabled is False
    assert policy.hourly_fetch_enabled is False
    assert policy.authoritative_daily_enabled is False
    assert schedule.enabled is False
    assert schedule.next_run_at is None
    assert queued_task.status == "blocked"
    assert db.query(OAuthEvent).filter_by(event_type="oauth_circuit_opened").count() == 1

    service._open_oauth_circuit(db, oauth_app=oauth_app, account_id=account.id)
    db.commit()
    db.refresh(policy)
    assert policy.resume_gray_enabled is True
    assert db.query(OAuthEvent).filter_by(event_type="oauth_circuit_opened").count() == 1


def test_successful_health_check_restores_only_invalid_grant_snapshot(tmp_path: Path) -> None:
    db = _session(tmp_path)
    account, instance, oauth_app, policy, schedule = _seed_account(db, runtime_status="degraded", excluded=True)
    health_task = CollectorSyncTask(
        account_id=account.id,
        collector_instance_id=instance.id,
        task_type="oauth_health_check",
        report_date=date(2026, 7, 29),
        status="in_progress",
        external_request_id="health-after-reauth",
    )
    db.add(health_task)
    db.commit()

    service.update_task_status(
        db,
        instance,
        health_task.id,
        schemas.TaskStatusUpdate(status="succeeded", message="oauth_health_check_succeeded"),
    )

    db.refresh(oauth_app)
    db.refresh(policy)
    db.refresh(schedule)
    assert oauth_app.runtime_status == "healthy"
    assert policy.exclusion_reason is None
    assert policy.gray_enabled is True
    assert policy.hourly_fetch_enabled is True
    assert policy.authoritative_daily_enabled is True
    assert policy.resume_gray_enabled is None
    assert schedule.enabled is True
    assert schedule.mode == "interval_hours"
    assert schedule.interval_hours == 4
    assert schedule.next_run_at is not None
    assert db.query(CollectorSyncTask).filter_by(task_type="report_fetch_hourly", status="pending").count() == 0
    assert db.query(OAuthEvent).filter_by(event_type="oauth_gap_scan_requested").count() == 1

    recovery_task = service.enqueue_next_oauth_recovery_gap(
        db,
        now=datetime(2026, 7, 31, 12, 0, tzinfo=UTC),
    )
    assert recovery_task is not None
    assert recovery_task.task_type == "report_fetch_hourly"
    assert recovery_task.run_reason == "oauth_recovery"


def test_health_recovery_does_not_clear_manual_stop(tmp_path: Path) -> None:
    db = _session(tmp_path)
    account, instance, oauth_app, policy, schedule = _seed_account(db, runtime_status="degraded", excluded=True)
    policy.exclusion_reason = "manual"
    policy.exclusion_note = "operator stop"
    db.commit()

    service._recover_oauth_after_health_check(db, oauth_app=oauth_app, account_id=account.id)
    db.commit()

    db.refresh(policy)
    db.refresh(schedule)
    assert policy.exclusion_reason == "manual"
    assert policy.gray_enabled is False
    assert policy.hourly_fetch_enabled is False
    assert schedule.enabled is False


@pytest.mark.parametrize(
    ("failure_class", "expected_status", "expected_reason"),
    [
        ("oauth_session_expired", "revoked", "invalid_grant"),
        ("oauth_client_invalid", "policy_blocked", "oauth_client_invalid"),
    ],
)
def test_non_retryable_oauth_failures_open_circuit_without_repeating_tasks(
    tmp_path: Path,
    failure_class: str,
    expected_status: str,
    expected_reason: str,
) -> None:
    db = _session(tmp_path)
    account, instance, oauth_app, policy, schedule = _seed_account(db)
    failed_task = CollectorSyncTask(
        account_id=account.id,
        collector_instance_id=instance.id,
        task_type="report_fetch_hourly",
        report_date=date(2026, 7, 30),
        status="in_progress",
        external_request_id=f"failed-{failure_class}",
    )
    db.add(failed_task)
    db.commit()

    service.update_task_status(
        db,
        instance,
        failed_task.id,
        schemas.TaskStatusUpdate(status="failed", failure_class=failure_class),
    )

    db.refresh(oauth_app)
    db.refresh(policy)
    db.refresh(schedule)
    assert oauth_app.runtime_status == expected_status
    assert oauth_app.failure_class == failure_class
    assert policy.exclusion_reason == expected_reason
    assert schedule.enabled is False
    assert db.query(CollectorSyncTask).filter_by(task_type="oauth_health_check", status="pending").count() == 0


@pytest.mark.parametrize(
    ("task_type", "run_reason"),
    [
        ("oauth_health_check", "automatic"),
        ("report_fetch_hourly", "oauth_recovery"),
    ],
)
def test_database_rejects_duplicate_active_oauth_control_tasks(
    tmp_path: Path,
    task_type: str,
    run_reason: str,
) -> None:
    db = _session(tmp_path)
    account, instance, _oauth_app, _policy, _schedule = _seed_account(db)
    first = CollectorSyncTask(
        account_id=account.id,
        collector_instance_id=instance.id,
        task_type=task_type,
        run_reason=run_reason,
        report_date=date(2026, 7, 29),
        status="pending",
        external_request_id=f"first-{task_type}-{run_reason}",
    )
    second = CollectorSyncTask(
        account_id=account.id,
        collector_instance_id=instance.id,
        task_type=task_type,
        run_reason=run_reason,
        report_date=date(2026, 7, 30),
        status="pending",
        external_request_id=f"second-{task_type}-{run_reason}",
    )
    db.add(first)
    db.commit()
    db.add(second)

    with pytest.raises(IntegrityError):
        db.commit()
