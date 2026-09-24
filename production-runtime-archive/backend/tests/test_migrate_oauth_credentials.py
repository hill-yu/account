from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.collectors import oauth_service
from app.collectors.credential_crypto import CredentialCipher, CredentialCryptoError
from app.database import Base
from app.models import Account, CollectorInstance, CollectorSyncTask, FetchSchedule, OAuthAppConfig, OAuthCredential
from app.scripts.migrate_oauth_credentials import migrate_oauth_credentials


def _session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, class_=Session)()


def _seed_legacy_app(db: Session, *, name: str, secret: str, refresh_token: str) -> OAuthAppConfig:
    account = Account(name=name, status="active")
    db.add(account)
    db.flush()
    instance = CollectorInstance(
        account_id=account.id,
        name=name.removesuffix(".com"),
        instance_token=f"instance-{name}",
        status="active",
        report_account_key=name.removesuffix(".com"),
    )
    db.add(instance)
    db.flush()
    db.add(
        FetchSchedule(
            account_id=account.id,
            collector_instance_id=instance.id,
            enabled=True,
            mode="interval",
            interval_hours=4,
            timezone="America/Los_Angeles",
            next_run_at=datetime.now(timezone.utc),
        )
    )
    oauth_app = OAuthAppConfig(
        account_id=account.id,
        client_id=f"client-{name}",
        client_secret=secret,
        redirect_uri=f"https://{name}/oauth/google/callback",
        scopes="https://www.googleapis.com/auth/admanager",
        authorization_status="authorized",
        flow_status="authorized",
        runtime_status="healthy",
        refresh_token=refresh_token,
        access_token=f"access-{name}",
        token_type="Bearer",
        granted_scopes="https://www.googleapis.com/auth/admanager",
    )
    db.add(oauth_app)
    db.commit()
    return oauth_app


def test_migrates_legacy_credentials_atomically_and_is_idempotent(
    credential_encryption_key: str,
    credential_fingerprint_key: str,
) -> None:
    db = _session()
    oauth_app = _seed_legacy_app(
        db,
        name="migrate-one.com",
        secret="legacy-secret-one",
        refresh_token="legacy-refresh-one",
    )
    cipher = CredentialCipher(
        encryption_key=credential_encryption_key,
        fingerprint_key=credential_fingerprint_key,
    )

    first_report = migrate_oauth_credentials(db, cipher=cipher)
    second_report = migrate_oauth_credentials(db, cipher=cipher)

    db.refresh(oauth_app)
    credentials = list(db.scalars(select(OAuthCredential).where(OAuthCredential.oauth_app_id == oauth_app.id)))
    tasks = list(db.scalars(select(CollectorSyncTask).where(CollectorSyncTask.account_id == oauth_app.account_id)))
    schedule = db.scalar(select(FetchSchedule).where(FetchSchedule.account_id == oauth_app.account_id))
    assert len(credentials) == 1
    assert credentials[0].version == 1
    assert credentials[0].status == "active"
    assert cipher.decrypt(credentials[0].client_secret_ciphertext) == "legacy-secret-one"
    assert cipher.decrypt(credentials[0].refresh_token_ciphertext) == "legacy-refresh-one"
    assert oauth_app.client_secret == ""
    assert oauth_app.refresh_token is None
    assert oauth_app.access_token is None
    assert oauth_app.access_token_expires_at is None
    assert oauth_app.token_type is None
    assert oauth_app.active_credential_version == 1
    assert oauth_app.runtime_status == "unknown"
    assert oauth_app.next_action == "validate_existing_credential"
    assert schedule is not None and schedule.enabled is False
    assert [(task.task_type, task.status) for task in tasks] == [("oauth_health_check", "pending")]
    assert first_report == second_report
    rendered_report = repr(first_report)
    assert set(first_report[0]) == {"account_id", "version", "fingerprint", "status"}
    assert "legacy-secret-one" not in rendered_report
    assert "legacy-refresh-one" not in rendered_report
    assert "access-migrate-one.com" not in rendered_report


def test_any_credential_readback_failure_rolls_back_all_accounts() -> None:
    db = _session()
    first = _seed_legacy_app(db, name="rollback-one.com", secret="secret-one", refresh_token="refresh-one")
    second = _seed_legacy_app(db, name="rollback-two.com", secret="secret-two", refresh_token="refresh-two")

    class FailingReadbackCipher:
        def encrypt(self, value: str) -> str:
            return f"encrypted:{value}"

        def decrypt(self, value: str) -> str:
            if value == "encrypted:refresh-two":
                raise CredentialCryptoError("CREDENTIAL_DECRYPT_FAILED")
            return value.removeprefix("encrypted:")

        def fingerprint(self, value: str) -> str:
            return f"fingerprint-{value[-3:]}"

    with pytest.raises(CredentialCryptoError, match="CREDENTIAL_DECRYPT_FAILED"):
        migrate_oauth_credentials(db, cipher=FailingReadbackCipher())  # type: ignore[arg-type]

    assert db.scalar(select(OAuthCredential)) is None
    assert db.scalar(select(CollectorSyncTask)) is None
    db.refresh(first)
    db.refresh(second)
    assert first.client_secret == "secret-one"
    assert first.refresh_token == "refresh-one"
    assert second.client_secret == "secret-two"
    assert second.refresh_token == "refresh-two"
    assert db.scalar(select(FetchSchedule).where(FetchSchedule.account_id == first.account_id)).enabled is True
    assert db.scalar(select(FetchSchedule).where(FetchSchedule.account_id == second.account_id)).enabled is True


def test_reauthorization_uses_encrypted_active_client_secret_after_migration(
    monkeypatch: pytest.MonkeyPatch,
    credential_encryption_key: str,
    credential_fingerprint_key: str,
) -> None:
    db = _session()
    oauth_app = _seed_legacy_app(
        db,
        name="reauthorize.com",
        secret="managed-client-secret",
        refresh_token="managed-refresh-token",
    )
    cipher = CredentialCipher(
        encryption_key=credential_encryption_key,
        fingerprint_key=credential_fingerprint_key,
    )
    migrate_oauth_credentials(db, cipher=cipher)
    posted_data: dict[str, str] = {}

    class Response:
        status_code = 200

        @staticmethod
        def json() -> dict[str, str]:
            return {
                "refresh_token": "replacement-refresh-token",
                "scope": "https://www.googleapis.com/auth/admanager",
            }

    def fake_post(url: str, *, data: dict[str, str], timeout: int) -> Response:
        del url, timeout
        posted_data.update(data)
        return Response()

    monkeypatch.setattr(oauth_service, "_credential_cipher", lambda: cipher)
    monkeypatch.setattr(oauth_service.requests, "post", fake_post)

    response = oauth_service._exchange_authorization_code(db, oauth_app=oauth_app, code="one-time-code")

    assert response.authorization_status == "validation_pending"
    assert posted_data["client_secret"] == "managed-client-secret"
    staged = db.scalar(
        select(OAuthCredential).where(
            OAuthCredential.oauth_app_id == oauth_app.id,
            OAuthCredential.status == "staged",
        )
    )
    assert staged is not None
    assert cipher.decrypt(staged.client_secret_ciphertext) == "managed-client-secret"
