from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app import models as _models  # noqa: F401
from app.collectors import fetch_policy, oauth_service, service
from app.collectors.credential_crypto import CredentialCipher
from app.database import Base
from app.models.account import Account
from app.models.collector_account_policy import CollectorAccountPolicy
from app.models.collector_instance import CollectorInstance
from app.models.collector_sync_task import CollectorSyncTask
from app.models.oauth_app_config import OAuthAppConfig
from app.models.oauth_credential import OAuthCredential
from app.models.oauth_event import OAuthEvent
from app.models.proxy_binding import ProxyBinding


@pytest.fixture()
def db_session(tmp_path: Path) -> Session:
    database_path = tmp_path / "oauth-service.db"
    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session)
    Base.metadata.create_all(engine)

    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture(autouse=True)
def credential_cipher(
    monkeypatch: pytest.MonkeyPatch,
    credential_encryption_key: str,
    credential_fingerprint_key: str,
) -> CredentialCipher:
    cipher = CredentialCipher(
        encryption_key=credential_encryption_key,
        fingerprint_key=credential_fingerprint_key,
    )
    monkeypatch.setattr(oauth_service, "_credential_cipher", lambda: cipher, raising=False)
    return cipher


class DummyResponse:
    def __init__(self, status_code: int, payload: dict[str, object]) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict[str, object]:
        return self._payload


def test_oauth_task_message_sanitizer_rejects_arbitrary_payload() -> None:
    assert service._sanitize_oauth_task_message("oauth_refresh_revoked") == "oauth_refresh_revoked"
    assert service._sanitize_oauth_task_message("secret-refresh-token") == "oauth_validation_failed"


def create_account_with_oauth_app(db_session: Session) -> OAuthAppConfig:
    account = Account(name="oauth-account", status="active", external_account_id="ext-oauth")
    db_session.add(account)
    db_session.commit()
    db_session.refresh(account)

    oauth_app = OAuthAppConfig(
        account_id=account.id,
        client_id="client-id",
        client_secret="",
        redirect_uri="https://control.example.com/api/v1/oauth/google/callback",
        scopes="https://www.googleapis.com/auth/dfp",
        pending_credential_version=1,
    )
    db_session.add(oauth_app)
    db_session.flush()
    cipher = oauth_service._credential_cipher()
    db_session.add(
        OAuthCredential(
            oauth_app_id=oauth_app.id,
            version=1,
            status="staged",
            client_secret_ciphertext=cipher.encrypt("client-secret"),
            refresh_token_ciphertext=None,
            token_fingerprint=None,
        )
    )
    db_session.commit()
    db_session.refresh(oauth_app)
    return oauth_app


def test_generate_authorization_url_persists_state_and_google_params(db_session: Session) -> None:
    oauth_app = create_account_with_oauth_app(db_session)

    authorization = oauth_service.generate_authorization_url(db_session, oauth_app.id)

    parsed = urlparse(authorization.authorization_url)
    query = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "accounts.google.com"
    assert parsed.path == "/o/oauth2/v2/auth"
    assert query["client_id"] == [oauth_app.client_id]
    assert query["redirect_uri"] == [oauth_app.redirect_uri]
    assert query["response_type"] == ["code"]
    assert query["scope"] == [oauth_app.scopes]
    assert query["state"] == [authorization.state]
    assert query["prompt"] == ["consent"]

    db_session.refresh(oauth_app)
    assert oauth_app.authorization_status == "authorization_requested"
    assert oauth_app.authorization_state == authorization.state
    assert oauth_app.authorization_requested_at is not None
    assert oauth_app.authorization_state_expires_at == authorization.state_expires_at


def test_healthy_account_requires_explicit_reauthorization_confirmation(db_session: Session) -> None:
    oauth_app = create_account_with_oauth_app(db_session)
    oauth_app.runtime_status = "healthy"
    oauth_app.active_credential_version = 1
    db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        oauth_service.generate_authorization_url(
            db_session,
            oauth_app.id,
            oauth_service.schemas.AuthorizationUrlRequest(),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "OAUTH_REAUTH_CONFIRMATION_REQUIRED"


def test_forced_reauthorization_requires_reason(db_session: Session) -> None:
    oauth_app = create_account_with_oauth_app(db_session)
    oauth_app.runtime_status = "healthy"
    oauth_app.active_credential_version = 1
    db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        oauth_service.generate_authorization_url(
            db_session,
            oauth_app.id,
            oauth_service.schemas.AuthorizationUrlRequest(force_reauthorize=True),
        )

    assert exc_info.value.detail["code"] == "OAUTH_REAUTH_REASON_REQUIRED"


def test_parallel_unexpired_authorization_state_is_rejected(db_session: Session) -> None:
    oauth_app = create_account_with_oauth_app(db_session)
    oauth_service.generate_authorization_url(db_session, oauth_app.id)

    with pytest.raises(HTTPException) as exc_info:
        oauth_service.generate_authorization_url(db_session, oauth_app.id)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "OAUTH_FLOW_ALREADY_ACTIVE"


@pytest.mark.parametrize("flow_status", ["exchanging", "validation_pending"])
def test_authorization_is_rejected_while_exchange_or_validation_is_active(
    db_session: Session,
    flow_status: str,
) -> None:
    oauth_app = create_account_with_oauth_app(db_session)
    oauth_app.flow_status = flow_status
    oauth_app.authorization_state = None
    oauth_app.authorization_state_expires_at = None
    db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        oauth_service.generate_authorization_url(db_session, oauth_app.id)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "OAUTH_FLOW_ALREADY_ACTIVE"


def test_new_oauth_app_encrypts_client_secret_without_legacy_plaintext(
    db_session: Session,
    credential_cipher: CredentialCipher,
) -> None:
    account = Account(name="new-encrypted-app", status="active")
    db_session.add(account)
    db_session.commit()

    oauth_app = oauth_service.create_oauth_app(
        db_session,
        oauth_service.schemas.OAuthAppCreate(
            account_id=account.id,
            client_id="new-client-id",
            client_secret="new-client-secret",
            redirect_uri="https://new.example/oauth/google/callback",
            scopes="https://www.googleapis.com/auth/admanager",
        ),
    )

    credential = db_session.query(OAuthCredential).filter_by(oauth_app_id=oauth_app.id, status="staged").one()
    assert oauth_app.client_secret == ""
    assert oauth_app.pending_credential_version == credential.version
    assert oauth_app.refresh_token_present is False
    assert credential_cipher.decrypt(credential.client_secret_ciphertext) == "new-client-secret"
    assert credential.refresh_token_ciphertext is None
    assert credential.token_fingerprint is None


def test_runtime_oauth_secret_resolution_rejects_unmigrated_legacy_secret(
    db_session: Session,
    credential_cipher: CredentialCipher,
) -> None:
    account = Account(name="legacy-oauth-account", status="active")
    db_session.add(account)
    db_session.flush()
    oauth_app = OAuthAppConfig(
        account_id=account.id,
        client_id="legacy-client-id",
        client_secret="legacy-client-secret",
        redirect_uri="https://control.example.com/api/v1/oauth/google/callback",
        scopes="https://www.googleapis.com/auth/dfp",
    )
    db_session.add(oauth_app)
    db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        oauth_service._resolve_oauth_client_secret(
            db_session,
            oauth_app=oauth_app,
            cipher=credential_cipher,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "OAUTH_CREDENTIAL_MIGRATION_REQUIRED"


def test_handle_google_callback_exchanges_code_and_persists_token_metadata(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    credential_cipher: CredentialCipher,
) -> None:
    oauth_app = create_account_with_oauth_app(db_session)
    pending_authorization = oauth_service.generate_authorization_url(db_session, oauth_app.id)
    token_calls: list[dict[str, object]] = []

    def fake_post(url: str, data: dict[str, str], timeout: int) -> DummyResponse:
        token_calls.append({"url": url, "data": data, "timeout": timeout})
        return DummyResponse(
            200,
            {
                "access_token": "access-token-123",
                "refresh_token": "refresh-token-456",
                "expires_in": 3600,
                "scope": oauth_app.scopes,
                "token_type": "Bearer",
            },
        )

    monkeypatch.setattr(oauth_service.requests, "post", fake_post)

    callback_result = oauth_service.handle_google_callback(
        db=db_session,
        state=pending_authorization.state,
        code="oauth-code-abc",
        issuer=oauth_service.GOOGLE_OAUTH_ISSUER,
    )

    assert token_calls == [
        {
            "url": oauth_service.GOOGLE_OAUTH_TOKEN_URL,
            "data": {
                "code": "oauth-code-abc",
                "client_id": oauth_app.client_id,
                    "client_secret": "client-secret",
                "redirect_uri": oauth_app.redirect_uri,
                "grant_type": "authorization_code",
            },
            "timeout": 30,
        }
    ]
    assert callback_result.oauth_app_id == oauth_app.id
    assert callback_result.account_id == oauth_app.account_id
    assert callback_result.authorization_status == "validation_pending"
    assert callback_result.refresh_token_present is True

    db_session.refresh(oauth_app)
    assert oauth_app.authorization_status == "validation_pending"
    assert oauth_app.flow_status == "validation_pending"
    assert oauth_app.pending_credential_version == 1
    assert oauth_app.authorization_state is None
    assert oauth_app.access_token is None
    assert oauth_app.refresh_token is None
    assert oauth_app.token_type is None
    assert oauth_app.granted_scopes == oauth_app.scopes
    assert oauth_app.authorization_completed_at is None

    staged = db_session.query(OAuthCredential).filter_by(oauth_app_id=oauth_app.id, status="staged").one()
    assert staged.version == 1
    assert credential_cipher.decrypt(staged.refresh_token_ciphertext) == "refresh-token-456"
    assert credential_cipher.decrypt(staged.client_secret_ciphertext) == "client-secret"
    assert staged.token_fingerprint == credential_cipher.fingerprint("refresh-token-456")


def test_handle_google_callback_rejects_invalid_state(db_session: Session) -> None:
    create_account_with_oauth_app(db_session)

    with pytest.raises(oauth_service.OAuthStateError):
        oauth_service.handle_google_callback(
            db=db_session,
            state="invalid-state",
            code="oauth-code",
            issuer=oauth_service.GOOGLE_OAUTH_ISSUER,
        )


def test_callback_consumes_state_before_token_exchange(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oauth_app = create_account_with_oauth_app(db_session)
    pending = oauth_service.generate_authorization_url(db_session, oauth_app.id)

    def exchange(*args, **kwargs):
        db_session.expire_all()
        claimed_app = db_session.get(OAuthAppConfig, oauth_app.id)
        assert claimed_app is not None
        assert claimed_app.authorization_state is None
        return DummyResponse(
            200,
            {
                "access_token": "temporary-access-token",
                "refresh_token": "new-refresh-token",
                "scope": oauth_app.scopes,
            },
        )

    monkeypatch.setattr(oauth_service.requests, "post", exchange)

    oauth_service.handle_google_callback(
        db_session,
        state=pending.state,
        code="one-time-code",
        issuer=oauth_service.GOOGLE_OAUTH_ISSUER,
    )

    with pytest.raises(oauth_service.OAuthStateError):
        oauth_service.handle_google_callback(
            db_session,
            state=pending.state,
            code="duplicate-code",
            issuer=oauth_service.GOOGLE_OAUTH_ISSUER,
        )


def test_import_google_callback_payload_exchanges_code_for_matching_redirect_uri(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oauth_app = create_account_with_oauth_app(db_session)
    pending_authorization = oauth_service.generate_authorization_url(db_session, oauth_app.id)

    def fake_post(url: str, data: dict[str, str], timeout: int) -> DummyResponse:
        assert url == oauth_service.GOOGLE_OAUTH_TOKEN_URL
        assert data["code"] == "oauth-json-code"
        assert data["redirect_uri"] == oauth_app.redirect_uri
        assert timeout == 30
        return DummyResponse(
            200,
            {
                "access_token": "json-access-token",
                "refresh_token": "json-refresh-token",
                "expires_in": 3600,
                "scope": oauth_app.scopes,
                "token_type": "Bearer",
            },
        )

    monkeypatch.setattr(oauth_service.requests, "post", fake_post)

    result = oauth_service.import_google_callback_payload(
        db_session,
        oauth_service.schemas.OAuthCallbackImportRequest(
            state=pending_authorization.state,
            code="oauth-json-code",
            redirect_uri=oauth_app.redirect_uri,
            callback_url=f"{oauth_app.redirect_uri}?state={pending_authorization.state}&code=oauth-json-code",
            iss=oauth_service.GOOGLE_OAUTH_ISSUER,
        ),
    )

    assert result.authorization_status == "validation_pending"
    assert result.refresh_token_present is True

    db_session.refresh(oauth_app)
    assert oauth_app.refresh_token is None
    assert oauth_app.pending_credential_version == 1


def test_revoked_callback_without_new_refresh_token_is_rejected_without_replacing_active(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oauth_app = create_account_with_oauth_app(db_session)
    oauth_app.runtime_status = "revoked"
    oauth_app.active_credential_version = 1
    oauth_app.pending_credential_version = None
    active_credential = db_session.query(OAuthCredential).filter_by(oauth_app_id=oauth_app.id, version=1).one()
    active_credential.status = "active"
    active_credential.refresh_token_ciphertext = oauth_service._credential_cipher().encrypt("old-refresh-token")
    active_credential.token_fingerprint = oauth_service._credential_cipher().fingerprint("old-refresh-token")
    db_session.commit()
    pending = oauth_service.generate_authorization_url(db_session, oauth_app.id)

    monkeypatch.setattr(
        oauth_service.requests,
        "post",
        lambda *args, **kwargs: DummyResponse(
            200,
            {
                "access_token": "temporary-access-token",
                "expires_in": 3600,
                "scope": oauth_app.scopes,
                "token_type": "Bearer",
            },
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        oauth_service.handle_google_callback(
            db_session,
            state=pending.state,
            code="code-without-refresh",
            issuer=oauth_service.GOOGLE_OAUTH_ISSUER,
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "OAUTH_REFRESH_TOKEN_MISSING"
    db_session.refresh(oauth_app)
    assert oauth_app.runtime_status == "revoked"
    assert oauth_app.active_credential_version == 1
    assert oauth_app.pending_credential_version is None
    assert db_session.query(OAuthCredential).filter_by(oauth_app_id=oauth_app.id, status="active").count() == 1


def test_failed_healthy_reauthorization_preserves_active_credential(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oauth_app = create_account_with_oauth_app(db_session)
    oauth_app.runtime_status = "healthy"
    oauth_app.active_credential_version = 1
    oauth_app.pending_credential_version = None
    active_credential = db_session.query(OAuthCredential).filter_by(oauth_app_id=oauth_app.id, version=1).one()
    active_credential.status = "active"
    active_credential.refresh_token_ciphertext = oauth_service._credential_cipher().encrypt("active-refresh-token")
    active_credential.token_fingerprint = oauth_service._credential_cipher().fingerprint("active-refresh-token")
    db_session.commit()
    pending = oauth_service.generate_authorization_url(
        db_session,
        oauth_app.id,
        oauth_service.schemas.AuthorizationUrlRequest(force_reauthorize=True, reason="operator_confirmed"),
    )
    monkeypatch.setattr(
        oauth_service.requests,
        "post",
        lambda *args, **kwargs: DummyResponse(400, {"error": "invalid_grant", "token": "must-not-be-stored"}),
    )

    with pytest.raises(HTTPException):
        oauth_service.handle_google_callback(
            db_session,
            state=pending.state,
            code="failed-code",
            issuer=oauth_service.GOOGLE_OAUTH_ISSUER,
        )

    db_session.refresh(oauth_app)
    assert oauth_app.runtime_status == "healthy"
    assert oauth_app.active_credential_version == 1
    assert db_session.query(OAuthCredential).filter_by(oauth_app_id=oauth_app.id, status="active").count() == 1
    assert "must-not-be-stored" not in (oauth_app.authorization_error or "")
    failed_event = db_session.query(OAuthEvent).filter_by(event_type="token_exchange_failed").one()
    assert failed_event.failure_class == "oauth_code_invalid"


def test_oauth_events_do_not_store_callback_secrets(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oauth_app = create_account_with_oauth_app(db_session)
    pending = oauth_service.generate_authorization_url(db_session, oauth_app.id)
    monkeypatch.setattr(
        oauth_service.requests,
        "post",
        lambda *args, **kwargs: DummyResponse(
            200,
            {"access_token": "secret-access", "refresh_token": "secret-refresh", "scope": oauth_app.scopes},
        ),
    )

    oauth_service.handle_google_callback(
        db_session,
        state=pending.state,
        code="secret-code",
        issuer=oauth_service.GOOGLE_OAUTH_ISSUER,
    )

    serialized = " ".join(
        str(
            {
                "event_type": event.event_type,
                "failure_class": event.failure_class,
                "metadata_json": event.metadata_json,
                "http_status": event.http_status,
            }
        )
        for event in db_session.query(OAuthEvent).all()
    )
    assert "secret-code" not in serialized
    assert "secret-access" not in serialized
    assert "secret-refresh" not in serialized


def test_oauth_list_exposes_managed_health_without_secret_fields(db_session: Session) -> None:
    oauth_app = create_account_with_oauth_app(db_session)
    oauth_app.flow_status = "completed"
    oauth_app.runtime_status = "degraded"
    oauth_app.active_credential_version = 4
    oauth_app.failure_class = "oauth_provider_unavailable"
    oauth_app.failure_count = 2
    oauth_app.next_action = "run_oauth_health_check"
    db_session.add(
        OAuthCredential(
            oauth_app_id=oauth_app.id,
            version=4,
            status="active",
            client_secret_ciphertext="must-not-be-returned-client-secret",
            refresh_token_ciphertext="must-not-be-returned-refresh-token",
            token_fingerprint="1234567890abcdef1234567890abcdef",
        )
    )
    db_session.commit()

    result = oauth_service.list_oauth_apps(db_session)

    assert len(result) == 1
    serialized = result[0].model_dump()
    assert serialized["flow_status"] == "completed"
    assert serialized["runtime_status"] == "degraded"
    assert serialized["active_credential_version"] == 4
    assert serialized["credential_fingerprint"] == "1234567890ab"
    assert serialized["failure_class"] == "oauth_provider_unavailable"
    assert serialized["failure_count"] == 2
    assert serialized["next_action"] == "run_oauth_health_check"
    assert "client_secret" not in serialized
    assert "refresh_token" not in serialized


def test_import_google_callback_payload_rejects_redirect_uri_mismatch(db_session: Session) -> None:
    oauth_app = create_account_with_oauth_app(db_session)
    pending_authorization = oauth_service.generate_authorization_url(db_session, oauth_app.id)

    with pytest.raises(HTTPException) as exc_info:
        oauth_service.import_google_callback_payload(
            db_session,
            oauth_service.schemas.OAuthCallbackImportRequest(
                state=pending_authorization.state,
                code="oauth-json-code",
                redirect_uri="https://wrong.example.com/oauth/google/callback",
                callback_url=(
                    "https://wrong.example.com/oauth/google/callback"
                    f"?state={pending_authorization.state}&code=oauth-json-code"
                ),
                iss=oauth_service.GOOGLE_OAUTH_ISSUER,
            ),
        )
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "redirect_uri mismatch"


def test_import_google_callback_payload_requires_google_issuer(db_session: Session) -> None:
    oauth_app = create_account_with_oauth_app(db_session)
    pending = oauth_service.generate_authorization_url(db_session, oauth_app.id)

    with pytest.raises(HTTPException) as exc_info:
        oauth_service.import_google_callback_payload(
            db_session,
            oauth_service.schemas.OAuthCallbackImportRequest(
                state=pending.state,
                code="oauth-json-code",
                redirect_uri=oauth_app.redirect_uri,
                callback_url=f"{oauth_app.redirect_uri}?state={pending.state}&code=oauth-json-code",
                iss=None,
            ),
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "issuer mismatch"


def test_public_callback_requires_google_issuer(db_session: Session) -> None:
    oauth_app = create_account_with_oauth_app(db_session)
    pending = oauth_service.generate_authorization_url(db_session, oauth_app.id)

    with pytest.raises(HTTPException) as exc_info:
        oauth_service.handle_google_callback(db_session, state=pending.state, code="code", issuer=None)

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "issuer mismatch"


def test_credential_ack_activates_exact_staged_version_and_creates_health_task(db_session: Session) -> None:
    oauth_app = create_account_with_oauth_app(db_session)
    account = db_session.get(Account, oauth_app.account_id)
    assert account is not None
    account.external_account_id = "network-123"
    oauth_app.flow_status = "validation_pending"
    oauth_app.authorization_status = "validation_pending"
    oauth_app.runtime_status = "revoked"
    oauth_app.active_credential_version = 1
    oauth_app.pending_credential_version = 2
    instance = CollectorInstance(
        account_id=account.id,
        name="credential-ack-node",
        instance_token="credential-ack-token",
        status="ready",
    )
    db_session.add_all(
        [
            instance,
            CollectorAccountPolicy(account_id=account.id, lifecycle_status="active"),
            OAuthCredential(
                oauth_app_id=oauth_app.id,
                version=2,
                status="staged",
                client_secret_ciphertext="new-client",
                refresh_token_ciphertext="new-refresh",
                token_fingerprint="new-fingerprint",
            ),
        ]
    )
    active_credential = db_session.query(OAuthCredential).filter_by(oauth_app_id=oauth_app.id, version=1).one()
    active_credential.status = "active"
    active_credential.refresh_token_ciphertext = oauth_service._credential_cipher().encrypt("old-refresh")
    active_credential.token_fingerprint = "old-fingerprint"
    db_session.flush()
    validation_task = CollectorSyncTask(
        account_id=account.id,
        collector_instance_id=instance.id,
        task_type="oauth_credential_validate",
        report_date=datetime.utcnow().date(),
        status="in_progress",
        credential_version=2,
        external_request_id="oauth-validate-test-v2",
    )
    db_session.add(validation_task)
    db_session.commit()

    with pytest.raises(HTTPException) as bad_fingerprint:
        oauth_service.acknowledge_credential_validation(
            db_session,
            instance=instance,
            payload=oauth_service.schemas.OAuthCredentialAckRequest(
                task_id=validation_task.id,
                account_id=account.id,
                credential_version=2,
                token_fingerprint="wrong-fingerprint",
                network_code="network-123",
                network_timezone="America/New_York",
                granted_scopes="https://www.googleapis.com/auth/admanager",
            ),
        )
    assert bad_fingerprint.value.detail["code"] == "STALE_CREDENTIAL_ACK"
    assert db_session.query(OAuthCredential).filter_by(oauth_app_id=oauth_app.id, version=2).one().status == "staged"

    result = oauth_service.acknowledge_credential_validation(
        db_session,
        instance=instance,
        payload=oauth_service.schemas.OAuthCredentialAckRequest(
            task_id=validation_task.id,
            account_id=account.id,
            credential_version=2,
            token_fingerprint="new-fingerprint",
            network_code="network-123",
            network_timezone="America/New_York",
            granted_scopes="https://www.googleapis.com/auth/admanager",
        ),
    )

    assert result.status == "activated"
    db_session.refresh(oauth_app)
    db_session.refresh(account)
    assert oauth_app.active_credential_version == 2
    assert oauth_app.pending_credential_version is None
    assert oauth_app.runtime_status == "degraded"
    assert oauth_app.flow_status == "completed"
    assert oauth_app.client_secret == ""
    assert account.timezone == "America/New_York"
    assert db_session.query(OAuthCredential).filter_by(oauth_app_id=oauth_app.id, version=1).one().status == "retired"
    assert db_session.query(OAuthCredential).filter_by(oauth_app_id=oauth_app.id, version=2).one().status == "active"
    assert db_session.query(CollectorSyncTask).filter_by(task_type="oauth_health_check", status="pending").count() == 1

    with pytest.raises(HTTPException) as exc_info:
        oauth_service.acknowledge_credential_validation(
            db_session,
            instance=instance,
            payload=oauth_service.schemas.OAuthCredentialAckRequest(
                task_id=validation_task.id,
                account_id=account.id,
                credential_version=2,
                token_fingerprint="new-fingerprint",
                network_code="network-123",
                network_timezone="America/New_York",
                granted_scopes="https://www.googleapis.com/auth/admanager",
            ),
        )
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "STALE_CREDENTIAL_ACK"


def test_rotated_credential_rejects_stale_task_status_without_mutating_task(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    credential_cipher: CredentialCipher,
) -> None:
    oauth_app = create_account_with_oauth_app(db_session)
    account = db_session.get(Account, oauth_app.account_id)
    assert account is not None
    instance = CollectorInstance(
        account_id=account.id,
        name="stale-version-node",
        instance_token="stale-version-token",
        status="ready",
    )
    oauth_app.flow_status = "completed"
    oauth_app.runtime_status = "healthy"
    oauth_app.active_credential_version = 2
    oauth_app.pending_credential_version = None
    db_session.add_all(
        [
            instance,
            CollectorAccountPolicy(
                account_id=account.id,
                lifecycle_status="active",
                gray_enabled=True,
                hourly_fetch_enabled=True,
                authoritative_daily_enabled=True,
                manual_fetch_enabled=True,
            ),
            OAuthCredential(
                oauth_app_id=oauth_app.id,
                version=2,
                status="active",
                client_secret_ciphertext=credential_cipher.encrypt("v2-client-secret"),
                refresh_token_ciphertext=credential_cipher.encrypt("v2-refresh-token"),
                token_fingerprint=credential_cipher.fingerprint("v2-refresh-token"),
            ),
        ]
    )
    db_session.flush()
    task = CollectorSyncTask(
        account_id=account.id,
        collector_instance_id=instance.id,
        task_type="report_fetch",
        report_date=datetime.utcnow().date(),
        status="in_progress",
        credential_version=1,
    )
    db_session.add(task)
    db_session.commit()
    monkeypatch.setattr(service, "assert_fetch_allowed", fetch_policy.assert_fetch_allowed)
    original_scalar = db_session.scalar
    original_execute = db_session.execute
    statements = []
    executed_statements = []

    def track_scalar(statement, *args, **kwargs):
        statements.append(statement)
        return original_scalar(statement, *args, **kwargs)

    def track_execute(statement, *args, **kwargs):
        executed_statements.append(statement)
        return original_execute(statement, *args, **kwargs)

    monkeypatch.setattr(db_session, "scalar", track_scalar)
    monkeypatch.setattr(db_session, "execute", track_execute)

    with pytest.raises(HTTPException) as exc_info:
        service.update_task_status(
            db_session,
            instance,
            task.id,
            oauth_service.schemas.TaskStatusUpdate(status="succeeded", credential_version=1),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "FETCH_CREDENTIAL_VERSION_MISMATCH"
    assert any(getattr(statement, "_for_update_arg", None) is not None for statement in statements)
    assert any(
        getattr(getattr(statement, "table", None), "name", None) == "oauth_app_configs"
        for statement in executed_statements
    )
    db_session.refresh(task)
    assert task.status == "in_progress"


def test_sqlite_oauth_app_write_guard_fails_closed_during_rotation(tmp_path: Path) -> None:
    """SQLite must serialize task writes with credential ACK, despite lacking FOR UPDATE."""
    database_path = tmp_path / "oauth-write-guard.db"
    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 0.01},
    )
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session)
    Base.metadata.create_all(engine)
    first = session_factory()
    second = session_factory()
    try:
        oauth_app = create_account_with_oauth_app(first)
        first.commit()

        assert service.acquire_oauth_app_write_guard(first, account_id=oauth_app.account_id) is not None
        with pytest.raises(HTTPException) as exc_info:
            service.acquire_oauth_app_write_guard(second, account_id=oauth_app.account_id)

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["code"] == "FETCH_CREDENTIAL_ROTATION_IN_PROGRESS"
    finally:
        first.rollback()
        second.rollback()
        first.close()
        second.close()
        engine.dispose()


def test_sqlite_oauth_app_write_guard_refreshes_after_committed_rotation(
    tmp_path: Path,
    credential_cipher: CredentialCipher,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A waiter must see the new version after the ACK holder commits."""
    monkeypatch.setattr(service, "assert_fetch_allowed", fetch_policy.assert_fetch_allowed)
    database_path = tmp_path / "oauth-write-guard-refresh.db"
    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 0.01},
    )
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session)
    Base.metadata.create_all(engine)
    rotator = session_factory()
    waiting_worker = session_factory()
    try:
        oauth_app = create_account_with_oauth_app(rotator)
        account = rotator.get(Account, oauth_app.account_id)
        assert account is not None
        instance = CollectorInstance(
            account_id=account.id,
            name="write-guard-refresh-node",
            instance_token="write-guard-refresh-token",
            status="ready",
        )
        rotator.add_all(
            [
                instance,
                CollectorAccountPolicy(account_id=account.id, lifecycle_status="active"),
            ]
        )
        credential_v1 = rotator.query(OAuthCredential).filter_by(oauth_app_id=oauth_app.id, version=1).one()
        credential_v1.status = "active"
        credential_v1.refresh_token_ciphertext = credential_cipher.encrypt("refresh-v1")
        credential_v1.token_fingerprint = credential_cipher.fingerprint("refresh-v1")
        oauth_app.flow_status = "completed"
        oauth_app.runtime_status = "healthy"
        oauth_app.active_credential_version = 1
        oauth_app.pending_credential_version = None
        rotator.flush()
        task = CollectorSyncTask(
            account_id=account.id,
            collector_instance_id=instance.id,
            task_type="report_fetch",
            report_date=datetime.utcnow().date(),
            status="in_progress",
            credential_version=1,
        )
        rotator.add(task)
        rotator.commit()

        worker_instance = waiting_worker.get(CollectorInstance, instance.id)
        worker_task = waiting_worker.get(CollectorSyncTask, task.id)
        cached_app = waiting_worker.get(OAuthAppConfig, oauth_app.id)
        assert worker_instance is not None and worker_task is not None and cached_app is not None
        assert cached_app.active_credential_version == 1

        credential_v1.status = "retired"
        rotator.add(
            OAuthCredential(
                oauth_app_id=oauth_app.id,
                version=2,
                status="active",
                client_secret_ciphertext=credential_cipher.encrypt("client-v2"),
                refresh_token_ciphertext=credential_cipher.encrypt("refresh-v2"),
                token_fingerprint=credential_cipher.fingerprint("refresh-v2"),
            )
        )
        oauth_app.active_credential_version = 2
        rotator.commit()

        guarded_app = service.acquire_oauth_app_write_guard(waiting_worker, account_id=account.id)
        assert guarded_app is not None
        assert guarded_app.active_credential_version == 2
        with pytest.raises(HTTPException) as exc_info:
            service._assert_task_credential_is_current(
                waiting_worker,
                instance=worker_instance,
                task=worker_task,
                supplied_version=1,
            )
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["code"] == "FETCH_CREDENTIAL_VERSION_MISMATCH"
    finally:
        rotator.rollback()
        waiting_worker.rollback()
        rotator.close()
        waiting_worker.close()
        engine.dispose()


def test_callback_creates_validation_task_for_existing_instance(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oauth_app = create_account_with_oauth_app(db_session)
    instance = CollectorInstance(
        account_id=oauth_app.account_id,
        name="callback-validation-node",
        instance_token="callback-validation-token",
        status="ready",
    )
    db_session.add(instance)
    db_session.commit()
    pending = oauth_service.generate_authorization_url(db_session, oauth_app.id)
    monkeypatch.setattr(
        oauth_service.requests,
        "post",
        lambda *args, **kwargs: DummyResponse(
            200,
            {
                "access_token": "memory-only-access-token",
                "refresh_token": "staged-refresh-token",
                "scope": "https://www.googleapis.com/auth/admanager",
                "token_type": "Bearer",
            },
        ),
    )

    oauth_service.handle_google_callback(
        db_session,
        state=pending.state,
        code="one-time-code",
        issuer=oauth_service.GOOGLE_OAUTH_ISSUER,
    )

    validation_task = db_session.query(CollectorSyncTask).filter_by(task_type="oauth_credential_validate").one()
    assert validation_task.account_id == oauth_app.account_id
    assert validation_task.collector_instance_id == instance.id
    assert validation_task.status == "pending"
    assert "memory-only-access-token" not in repr(validation_task.__dict__)


def test_runtime_config_uses_encrypted_active_credential(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    credential_cipher: CredentialCipher,
) -> None:
    oauth_app = create_account_with_oauth_app(db_session)
    account = db_session.get(Account, oauth_app.account_id)
    assert account is not None
    account.external_account_id = "network-123"
    oauth_app.authorization_status = "authorized"
    oauth_app.runtime_status = "healthy"
    oauth_app.active_credential_version = 3
    instance = CollectorInstance(
        account_id=account.id,
        name="managed-runtime-node",
        instance_token="managed-runtime-token",
        status="ready",
    )
    db_session.add(instance)
    db_session.flush()
    db_session.add_all(
        [
            CollectorAccountPolicy(
                account_id=account.id,
                lifecycle_status="active",
                gray_enabled=True,
                hourly_fetch_enabled=True,
                authoritative_daily_enabled=True,
                manual_fetch_enabled=True,
            ),
            ProxyBinding(
                account_id=account.id,
                collector_instance_id=instance.id,
                provider_name="proxyco",
                protocol="socks5",
                host="proxy.example.com",
                port=5001,
                username="proxy-user",
                password="proxy-password",
                expected_egress_ip="203.0.113.10",
                status="active",
            ),
            OAuthCredential(
                oauth_app_id=oauth_app.id,
                version=3,
                status="active",
                client_secret_ciphertext=credential_cipher.encrypt("managed-client-secret"),
                refresh_token_ciphertext=credential_cipher.encrypt("managed-refresh-token"),
                token_fingerprint=credential_cipher.fingerprint("managed-refresh-token"),
                granted_scopes="https://www.googleapis.com/auth/admanager",
            ),
        ]
    )
    db_session.commit()
    monkeypatch.setattr(
        service,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "credential_encryption_key": "test-encryption-key",
                "credential_fingerprint_key": "test-fingerprint-key",
            },
        )(),
    )
    monkeypatch.setattr(service, "CredentialCipher", lambda **kwargs: credential_cipher)

    runtime = service.build_runtime_config(
        db_session,
        instance,
        control_plane_base_url="https://control.example.com",
    )

    assert runtime.google.fetch_mode == "admanager_soap"
    assert runtime.google.operation == "fetch"
    assert runtime.google.credential_version == 3
    assert runtime.google.google_oauth_client_secret == "managed-client-secret"
    assert runtime.google.google_oauth_refresh_token == "managed-refresh-token"


def test_runtime_config_rejects_legacy_plaintext_oauth_without_managed_version(db_session: Session) -> None:
    oauth_app = create_account_with_oauth_app(db_session)
    account = db_session.get(Account, oauth_app.account_id)
    assert account is not None
    account.external_account_id = "network-legacy"
    oauth_app.authorization_status = "authorized"
    oauth_app.runtime_status = "healthy"
    oauth_app.refresh_token = "legacy-refresh-token"
    instance = CollectorInstance(
        account_id=account.id,
        name="legacy-runtime-node",
        instance_token="legacy-runtime-token",
        status="ready",
    )
    db_session.add(instance)
    db_session.flush()
    db_session.add(
        ProxyBinding(
            account_id=account.id,
            collector_instance_id=instance.id,
            provider_name="proxyco",
            protocol="socks5",
            host="proxy.example.com",
            port=5001,
            username="proxy-user",
            password="proxy-password",
            expected_egress_ip="203.0.113.20",
            status="active",
        )
    )
    db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        service.build_runtime_config(
            db_session,
            instance,
            control_plane_base_url="https://control.example.com",
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Managed OAuth credential is required for runtime fetch"
