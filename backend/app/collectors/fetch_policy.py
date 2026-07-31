from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.collector_account_policy import CollectorAccountPolicy
from app.models.oauth_app_config import OAuthAppConfig
from app.models.oauth_credential import OAuthCredential


MANUAL_FETCH_KINDS = {"operator_task", "manual_hourly", "targeted_recent"}
RUNTIME_FETCH_KINDS = {"claim", "batch", "terminal_status"}


def assert_fetch_allowed(
    db: Session,
    *,
    account_id: int,
    fetch_kind: str,
    credential_version: int | None = None,
) -> CollectorAccountPolicy:
    policy = db.scalar(select(CollectorAccountPolicy).where(CollectorAccountPolicy.account_id == account_id))
    if policy is None:
        _deny("FETCH_POLICY_MISSING")

    oauth_app = db.scalar(select(OAuthAppConfig).where(OAuthAppConfig.account_id == account_id))
    if oauth_app is None:
        _deny("FETCH_OAUTH_APP_MISSING")

    if fetch_kind == "oauth_credential_validate":
        _assert_validation_allowed(db, policy=policy, oauth_app=oauth_app, credential_version=credential_version)
        return policy

    if fetch_kind == "oauth_health_check":
        _assert_health_check_allowed(db, policy=policy, oauth_app=oauth_app, credential_version=credential_version)
        return policy

    if policy.lifecycle_status != "active":
        _deny("FETCH_POLICY_LIFECYCLE_BLOCKED")
    if policy.exclusion_reason is not None:
        _deny("FETCH_POLICY_EXCLUDED")

    if fetch_kind in MANUAL_FETCH_KINDS and not policy.manual_fetch_enabled:
        _deny("FETCH_POLICY_MANUAL_DISABLED")
    if fetch_kind == "automatic_hourly" and (not policy.gray_enabled or not policy.hourly_fetch_enabled):
        _deny("FETCH_POLICY_HOURLY_DISABLED")
    if fetch_kind == "automatic_daily" and (
        not policy.gray_enabled or not policy.authoritative_daily_enabled
    ):
        _deny("FETCH_POLICY_DAILY_DISABLED")
    if fetch_kind not in MANUAL_FETCH_KINDS | RUNTIME_FETCH_KINDS | {"automatic_hourly", "automatic_daily"}:
        _deny("FETCH_KIND_UNSUPPORTED")

    if oauth_app.runtime_status != "healthy" or oauth_app.active_credential_version is None:
        _deny("FETCH_OAUTH_NOT_HEALTHY")
    _assert_credential(
        db,
        oauth_app_id=oauth_app.id,
        expected_version=oauth_app.active_credential_version,
        expected_status="active",
        supplied_version=credential_version,
    )
    return policy


def _assert_validation_allowed(
    db: Session,
    *,
    policy: CollectorAccountPolicy,
    oauth_app: OAuthAppConfig,
    credential_version: int | None,
) -> None:
    if policy.lifecycle_status == "retired" or policy.exclusion_reason in {"manual", "account_banned", "retired"}:
        _deny("FETCH_POLICY_EXCLUDED")
    if oauth_app.flow_status != "validation_pending" or oauth_app.pending_credential_version is None:
        _deny("FETCH_VALIDATION_NOT_PENDING")
    _assert_credential(
        db,
        oauth_app_id=oauth_app.id,
        expected_version=oauth_app.pending_credential_version,
        expected_status="staged",
        supplied_version=credential_version,
    )


def _assert_health_check_allowed(
    db: Session,
    *,
    policy: CollectorAccountPolicy,
    oauth_app: OAuthAppConfig,
    credential_version: int | None,
) -> None:
    if policy.lifecycle_status != "active" or policy.exclusion_reason not in {None, "invalid_grant"}:
        _deny("FETCH_POLICY_EXCLUDED")
    if oauth_app.runtime_status not in {"degraded", "revoked"} or oauth_app.active_credential_version is None:
        _deny("FETCH_HEALTH_CHECK_NOT_ALLOWED")
    _assert_credential(
        db,
        oauth_app_id=oauth_app.id,
        expected_version=oauth_app.active_credential_version,
        expected_status="active",
        supplied_version=credential_version,
    )


def _assert_credential(
    db: Session,
    *,
    oauth_app_id: int,
    expected_version: int,
    expected_status: str,
    supplied_version: int | None,
) -> None:
    if supplied_version is not None and supplied_version != expected_version:
        _deny("FETCH_CREDENTIAL_VERSION_MISMATCH")
    credential = db.scalar(
        select(OAuthCredential).where(
            OAuthCredential.oauth_app_id == oauth_app_id,
            OAuthCredential.version == expected_version,
            OAuthCredential.status == expected_status,
        )
    )
    if credential is None:
        _deny("FETCH_CREDENTIAL_NOT_AVAILABLE")


def _deny(code: str) -> None:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": code, "message": "Data fetch is not allowed for this account"},
    )
