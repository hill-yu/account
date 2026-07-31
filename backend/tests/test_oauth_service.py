from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app import models as _models  # noqa: F401
from app.collectors import oauth_service
from app.database import Base
from app.models.account import Account
from app.models.oauth_app_config import OAuthAppConfig


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


class DummyResponse:
    def __init__(self, status_code: int, payload: dict[str, object]) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict[str, object]:
        return self._payload


def create_account_with_oauth_app(db_session: Session) -> OAuthAppConfig:
    account = Account(name="oauth-account", status="active", external_account_id="ext-oauth")
    db_session.add(account)
    db_session.commit()
    db_session.refresh(account)

    oauth_app = OAuthAppConfig(
        account_id=account.id,
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="https://control.example.com/api/v1/oauth/google/callback",
        scopes="https://www.googleapis.com/auth/dfp",
    )
    db_session.add(oauth_app)
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

    db_session.refresh(oauth_app)
    assert oauth_app.authorization_status == "authorization_requested"
    assert oauth_app.authorization_state == authorization.state
    assert oauth_app.authorization_requested_at is not None
    assert oauth_app.authorization_state_expires_at == authorization.state_expires_at


def test_handle_google_callback_exchanges_code_and_persists_token_metadata(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
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
    )

    assert token_calls == [
        {
            "url": oauth_service.GOOGLE_OAUTH_TOKEN_URL,
            "data": {
                "code": "oauth-code-abc",
                "client_id": oauth_app.client_id,
                "client_secret": oauth_app.client_secret,
                "redirect_uri": oauth_app.redirect_uri,
                "grant_type": "authorization_code",
            },
            "timeout": 30,
        }
    ]
    assert callback_result.oauth_app_id == oauth_app.id
    assert callback_result.account_id == oauth_app.account_id
    assert callback_result.authorization_status == "authorized"
    assert callback_result.refresh_token_present is True

    db_session.refresh(oauth_app)
    assert oauth_app.authorization_status == "authorized"
    assert oauth_app.authorization_state is None
    assert oauth_app.access_token == "access-token-123"
    assert oauth_app.refresh_token == "refresh-token-456"
    assert oauth_app.token_type == "Bearer"
    assert oauth_app.granted_scopes == oauth_app.scopes
    assert oauth_app.authorization_completed_at is not None
    assert oauth_app.refresh_token_updated_at is not None
    assert oauth_app.access_token_expires_at is not None
    assert oauth_app.access_token_expires_at > datetime.utcnow() + timedelta(minutes=50)


def test_handle_google_callback_rejects_invalid_state(db_session: Session) -> None:
    create_account_with_oauth_app(db_session)

    with pytest.raises(oauth_service.OAuthStateError):
        oauth_service.handle_google_callback(db=db_session, state="invalid-state", code="oauth-code")


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
        ),
    )

    assert result.authorization_status == "authorized"
    assert result.refresh_token_present is True

    db_session.refresh(oauth_app)
    assert oauth_app.refresh_token == "json-refresh-token"


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
            ),
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "redirect_uri mismatch"
