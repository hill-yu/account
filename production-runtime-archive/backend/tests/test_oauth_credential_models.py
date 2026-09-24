from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models as _models  # noqa: F401
from app.database import Base
from app.models.account import Account
from app.models.collector_account_policy import CollectorAccountPolicy
from app.models.oauth_app_config import OAuthAppConfig
from app.models.oauth_credential import OAuthCredential
from app.models.oauth_event import OAuthEvent


@pytest.fixture()
def db_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _create_oauth_app(db_session: Session) -> OAuthAppConfig:
    account = Account(name="credential-model-account", status="active")
    db_session.add(account)
    db_session.flush()
    oauth_app = OAuthAppConfig(
        account_id=account.id,
        client_id="client-id",
        client_secret="legacy-client-secret",
        redirect_uri="https://example.com/oauth/google/callback",
        scopes="https://www.googleapis.com/auth/admanager",
    )
    db_session.add(oauth_app)
    db_session.commit()
    return oauth_app


def _credential(oauth_app_id: int, *, version: int, status: str) -> OAuthCredential:
    return OAuthCredential(
        oauth_app_id=oauth_app_id,
        version=version,
        status=status,
        client_secret_ciphertext=f"encrypted-client-secret-{version}",
        refresh_token_ciphertext=f"encrypted-refresh-token-{version}",
        token_fingerprint=f"fingerprint-{version}",
        granted_scopes="https://www.googleapis.com/auth/admanager",
    )


def test_oauth_app_allows_one_active_and_one_staged_credential(db_session: Session) -> None:
    oauth_app = _create_oauth_app(db_session)
    db_session.add_all(
        [
            _credential(oauth_app.id, version=1, status="active"),
            _credential(oauth_app.id, version=2, status="staged"),
        ]
    )
    db_session.commit()

    assert [(item.version, item.status) for item in oauth_app.credentials] == [(1, "active"), (2, "staged")]

    db_session.add(_credential(oauth_app.id, version=3, status="active"))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_account_policy_rejects_gray_with_exclusion_reason(db_session: Session) -> None:
    account = Account(name="excluded-gray-account", status="active")
    db_session.add(account)
    db_session.flush()
    db_session.add(
        CollectorAccountPolicy(
            account_id=account.id,
            lifecycle_status="active",
            gray_enabled=True,
            hourly_fetch_enabled=True,
            authoritative_daily_enabled=True,
            manual_fetch_enabled=True,
            exclusion_reason="invalid_grant",
        )
    )

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_oauth_event_has_no_secret_payload_columns() -> None:
    columns = {column.name for column in inspect(OAuthEvent).columns}
    forbidden = {
        "authorization_code",
        "callback_url",
        "client_secret",
        "refresh_token",
        "access_token",
        "payload",
    }

    assert columns.isdisjoint(forbidden)
    assert {
        "account_id",
        "oauth_app_id",
        "event_type",
        "credential_version",
        "failure_class",
        "http_status",
        "metadata_json",
        "created_at",
    }.issubset(columns)


def test_oauth_app_exposes_flow_and_runtime_health_fields(db_session: Session) -> None:
    oauth_app = _create_oauth_app(db_session)

    assert oauth_app.flow_status == "pending"
    assert oauth_app.runtime_status == "unknown"
    assert oauth_app.failure_count == 0
    assert oauth_app.publishing_status == "in_production"
    assert oauth_app.active_credential_version is None
    assert oauth_app.pending_credential_version is None
    assert oauth_app.last_verified_at is None
    assert oauth_app.revoked_at is None
    assert oauth_app.next_action is None
    assert isinstance(oauth_app.created_at, datetime)
