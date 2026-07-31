from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import models as _models  # noqa: F401
from app.collectors.fetch_policy import assert_fetch_allowed
from app.collectors.service import list_account_daily_reports
from app.database import Base
from app.models.account import Account
from app.models.account_daily_report import AccountDailyReport
from app.models.collector_account_policy import CollectorAccountPolicy
from app.models.oauth_app_config import OAuthAppConfig
from app.models.oauth_credential import OAuthCredential


@pytest.fixture()
def policy_db() -> tuple[Session, int]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        account = Account(name="fetch-policy-account", status="active")
        session.add(account)
        session.flush()
        oauth_app = OAuthAppConfig(
            account_id=account.id,
            client_id="client-id",
            client_secret="legacy-client-secret",
            redirect_uri="https://example.com/oauth/google/callback",
            scopes="https://www.googleapis.com/auth/admanager",
            runtime_status="healthy",
            flow_status="completed",
            active_credential_version=1,
            last_verified_at=datetime.utcnow(),
        )
        session.add(oauth_app)
        session.flush()
        session.add_all(
            [
                OAuthCredential(
                    oauth_app_id=oauth_app.id,
                    version=1,
                    status="active",
                    client_secret_ciphertext="encrypted-client-secret",
                    refresh_token_ciphertext="encrypted-refresh-token",
                    token_fingerprint="fingerprint",
                ),
                CollectorAccountPolicy(
                    account_id=account.id,
                    lifecycle_status="active",
                    gray_enabled=True,
                    hourly_fetch_enabled=True,
                    authoritative_daily_enabled=True,
                    manual_fetch_enabled=True,
                ),
            ]
        )
        session.commit()
        yield session, account.id
    engine.dispose()


@pytest.mark.parametrize(
    "entrypoint",
    [
        "operator_task",
        "manual_hourly",
        "targeted_recent",
        "automatic_hourly",
        "automatic_daily",
        "claim",
        "batch",
        "terminal_status",
    ],
)
def test_revoked_account_is_blocked_at_every_fetch_entrypoint(
    policy_db: tuple[Session, int],
    entrypoint: str,
) -> None:
    db, account_id = policy_db
    policy = db.query(CollectorAccountPolicy).filter_by(account_id=account_id).one()
    policy.gray_enabled = False
    policy.exclusion_reason = "invalid_grant"
    oauth_app = db.query(OAuthAppConfig).filter_by(account_id=account_id).one()
    oauth_app.runtime_status = "revoked"
    db.commit()

    with pytest.raises(HTTPException) as exc_info:
        assert_fetch_allowed(db, account_id=account_id, fetch_kind=entrypoint, credential_version=1)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "FETCH_POLICY_EXCLUDED"


def test_healthy_account_with_matching_active_version_is_allowed(policy_db: tuple[Session, int]) -> None:
    db, account_id = policy_db

    policy = assert_fetch_allowed(
        db,
        account_id=account_id,
        fetch_kind="automatic_hourly",
        credential_version=1,
    )

    assert policy.gray_enabled is True
    assert policy.hourly_fetch_enabled is True


def test_manual_exclusion_is_never_bypassed_by_healthy_oauth(policy_db: tuple[Session, int]) -> None:
    db, account_id = policy_db
    policy = db.query(CollectorAccountPolicy).filter_by(account_id=account_id).one()
    policy.gray_enabled = False
    policy.exclusion_reason = "manual"
    db.commit()

    with pytest.raises(HTTPException) as exc_info:
        assert_fetch_allowed(db, account_id=account_id, fetch_kind="manual_hourly", credential_version=1)

    assert exc_info.value.detail["code"] == "FETCH_POLICY_EXCLUDED"


def test_validation_only_accepts_current_staged_version(policy_db: tuple[Session, int]) -> None:
    db, account_id = policy_db
    oauth_app = db.query(OAuthAppConfig).filter_by(account_id=account_id).one()
    oauth_app.runtime_status = "revoked"
    oauth_app.flow_status = "validation_pending"
    oauth_app.pending_credential_version = 2
    db.add(
        OAuthCredential(
            oauth_app_id=oauth_app.id,
            version=2,
            status="staged",
            client_secret_ciphertext="staged-client-secret",
            refresh_token_ciphertext="staged-refresh-token",
            token_fingerprint="staged-fingerprint",
        )
    )
    db.commit()

    assert_fetch_allowed(db, account_id=account_id, fetch_kind="oauth_credential_validate", credential_version=2)

    with pytest.raises(HTTPException) as exc_info:
        assert_fetch_allowed(db, account_id=account_id, fetch_kind="oauth_credential_validate", credential_version=1)
    assert exc_info.value.detail["code"] == "FETCH_CREDENTIAL_VERSION_MISMATCH"


def test_excluded_account_can_still_read_historical_reports(policy_db: tuple[Session, int]) -> None:
    db, account_id = policy_db
    policy = db.query(CollectorAccountPolicy).filter_by(account_id=account_id).one()
    policy.gray_enabled = False
    policy.exclusion_reason = "manual"
    db.add(
        AccountDailyReport(
            account_id=account_id,
            report_date=date(2026, 7, 29),
            responses_served=10,
            requests=12,
            impressions=8,
            clicks=1,
            revenue=Decimal("1.000000"),
            ecpm=Decimal("125.000000"),
        )
    )
    db.commit()

    rows = list_account_daily_reports(db, account_id=account_id, report_date=date(2026, 7, 29))

    assert len(rows) == 1
    assert rows[0].requests == 12
