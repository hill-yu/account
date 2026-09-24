from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Account, CollectorAccountPolicy, CollectorInstance, FetchSchedule
from app.scripts.migrate_collector_account_policies import migrate_collector_account_policies


def _session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, class_=Session)()


def _seed_account(db: Session, *, key: str, schedule_enabled: bool = True) -> Account:
    account = Account(name=f"{key}.com", status="active")
    db.add(account)
    db.flush()
    instance = CollectorInstance(
        account_id=account.id,
        name=key,
        instance_token=f"instance-{key}",
        status="active",
        report_account_key=key,
    )
    db.add(instance)
    db.flush()
    db.add(
        FetchSchedule(
            account_id=account.id,
            collector_instance_id=instance.id,
            enabled=schedule_enabled,
            mode="interval",
            interval_hours=4,
            timezone="America/Los_Angeles",
        )
    )
    db.commit()
    return account


def test_policy_migration_maps_gray_manual_and_schedule_and_is_idempotent() -> None:
    db = _session()
    gray = _seed_account(db, key="gray", schedule_enabled=True)
    manual = _seed_account(db, key="manual", schedule_enabled=True)
    ordinary = _seed_account(db, key="ordinary", schedule_enabled=False)

    first_report = migrate_collector_account_policies(
        db,
        gray_account_keys={"gray"},
        invalid_grant_account_keys=set(),
        manual_account_keys={"manual"},
    )
    second_report = migrate_collector_account_policies(
        db,
        gray_account_keys={"gray"},
        invalid_grant_account_keys=set(),
        manual_account_keys={"manual"},
    )

    policies = {
        policy.account_id: policy
        for policy in db.scalars(select(CollectorAccountPolicy).order_by(CollectorAccountPolicy.account_id))
    }
    assert len(policies) == 3
    assert policies[gray.id].gray_enabled is True
    assert policies[gray.id].hourly_fetch_enabled is True
    assert policies[gray.id].authoritative_daily_enabled is True
    assert policies[gray.id].manual_fetch_enabled is True
    assert policies[gray.id].exclusion_reason is None
    assert policies[manual.id].gray_enabled is False
    assert policies[manual.id].hourly_fetch_enabled is False
    assert policies[manual.id].authoritative_daily_enabled is False
    assert policies[manual.id].manual_fetch_enabled is False
    assert policies[manual.id].exclusion_reason == "manual"
    assert policies[ordinary.id].gray_enabled is False
    assert policies[ordinary.id].hourly_fetch_enabled is False
    assert policies[ordinary.id].authoritative_daily_enabled is False
    assert policies[ordinary.id].manual_fetch_enabled is True
    assert policies[ordinary.id].exclusion_reason is None
    assert first_report == second_report
    assert all(set(item) == {"account_id", "policy_status"} for item in first_report)


def test_policy_conflict_aborts_without_writing_any_account() -> None:
    db = _session()
    _seed_account(db, key="conflicted")
    _seed_account(db, key="unrelated")

    try:
        migrate_collector_account_policies(
            db,
            gray_account_keys={"conflicted"},
            invalid_grant_account_keys=set(),
            manual_account_keys={"conflicted"},
        )
    except ValueError as exc:
        assert str(exc) == "POLICY_ACCOUNT_SET_CONFLICT:conflicted"
    else:
        raise AssertionError("policy conflict must abort migration")

    assert db.scalar(select(CollectorAccountPolicy)) is None
