from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collectors.service import (
    INVALID_GRANT_DO_NOT_FETCH_ACCOUNT_KEYS,
    MANUAL_DO_NOT_FETCH_ACCOUNT_KEYS,
    TARGETED_BACKFILL_ACCOUNT_KEYS,
)
from app.database import get_session_factory
from app.models import Account, CollectorAccountPolicy, CollectorInstance, FetchSchedule


def _normalize_account_keys(values: set[str] | tuple[str, ...]) -> set[str]:
    return {value.strip().lower() for value in values if value.strip()}


def _policy_status(policy: CollectorAccountPolicy) -> str:
    if policy.exclusion_reason:
        return f"excluded_{policy.exclusion_reason}"
    if policy.gray_enabled:
        return "gray_enabled"
    return "manual_only"


def migrate_collector_account_policies(
    db: Session,
    *,
    gray_account_keys: set[str] | tuple[str, ...] = TARGETED_BACKFILL_ACCOUNT_KEYS,
    invalid_grant_account_keys: set[str] | tuple[str, ...] = INVALID_GRANT_DO_NOT_FETCH_ACCOUNT_KEYS,
    manual_account_keys: set[str] | tuple[str, ...] = MANUAL_DO_NOT_FETCH_ACCOUNT_KEYS,
) -> list[dict[str, object]]:
    """Create initial database policies from legacy account sets and schedules."""
    gray_keys = _normalize_account_keys(gray_account_keys)
    invalid_keys = _normalize_account_keys(invalid_grant_account_keys)
    manual_keys = _normalize_account_keys(manual_account_keys)
    conflicts = (gray_keys & (invalid_keys | manual_keys)) | (invalid_keys & manual_keys)
    if conflicts:
        raise ValueError(f"POLICY_ACCOUNT_SET_CONFLICT:{','.join(sorted(conflicts))}")

    report: list[dict[str, object]] = []
    with db.begin():
        rows = db.execute(
            select(Account, CollectorInstance, FetchSchedule)
            .join(CollectorInstance, CollectorInstance.account_id == Account.id)
            .outerjoin(FetchSchedule, FetchSchedule.account_id == Account.id)
            .order_by(Account.id)
        ).all()
        for account, instance, schedule in rows:
            account_key = (instance.report_account_key or instance.name).strip().lower()
            policy = db.scalar(
                select(CollectorAccountPolicy).where(CollectorAccountPolicy.account_id == account.id)
            )
            if policy is None:
                exclusion_reason: str | None = None
                if account_key in invalid_keys:
                    exclusion_reason = "invalid_grant"
                elif account_key in manual_keys:
                    exclusion_reason = "manual"
                gray_enabled = account_key in gray_keys and exclusion_reason is None
                lifecycle_status = "active" if account.status == "active" else "onboarding"
                policy = CollectorAccountPolicy(
                    account_id=account.id,
                    lifecycle_status=lifecycle_status,
                    gray_enabled=gray_enabled,
                    hourly_fetch_enabled=bool(gray_enabled and schedule is not None and schedule.enabled),
                    authoritative_daily_enabled=gray_enabled,
                    manual_fetch_enabled=lifecycle_status == "active" and exclusion_reason is None,
                    exclusion_reason=exclusion_reason,
                    exclusion_note="migrated_from_legacy_account_sets" if exclusion_reason else None,
                )
                db.add(policy)
                db.flush()
            report.append({"account_id": account.id, "policy_status": _policy_status(policy)})
    return report


def main() -> None:
    with get_session_factory()() as db:
        report = migrate_collector_account_policies(db)
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))


if __name__ == "__main__":
    main()
