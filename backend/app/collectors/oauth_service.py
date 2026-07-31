from __future__ import annotations

from datetime import datetime, timedelta
import json
from secrets import token_urlsafe
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from fastapi import HTTPException, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.collectors import schemas, service
from app.collectors.credential_crypto import CredentialCipher
from app.config import get_settings
from app.models.account import Account
from app.models.oauth_app_config import OAuthAppConfig
from app.models.oauth_credential import OAuthCredential
from app.models.oauth_event import OAuthEvent


GOOGLE_OAUTH_AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_OAUTH_ISSUER = "https://accounts.google.com"
OAUTH_STATE_TTL = timedelta(minutes=10)


class OAuthStateError(Exception):
    pass


def utcnow() -> datetime:
    return datetime.utcnow()


def list_oauth_apps(db: Session) -> list[OAuthAppConfig]:
    return list(db.scalars(select(OAuthAppConfig).order_by(OAuthAppConfig.id)))


def create_oauth_app(db: Session, payload: schemas.OAuthAppCreate) -> OAuthAppConfig:
    account = db.get(Account, payload.account_id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    oauth_app = OAuthAppConfig(
        account_id=payload.account_id,
        client_id=payload.client_id,
        client_secret=payload.client_secret,
        redirect_uri=payload.redirect_uri,
        scopes=payload.scopes,
        app_status=payload.app_status,
        verification_status=payload.verification_status,
    )
    db.add(oauth_app)
    service.commit_or_raise_conflict(db, "OAuth app already exists for this account")
    db.refresh(oauth_app)
    return oauth_app


def generate_authorization_url(
    db: Session,
    oauth_app_id: int,
    payload: schemas.AuthorizationUrlRequest | None = None,
) -> schemas.AuthorizationUrlResponse:
    oauth_app = db.get(OAuthAppConfig, oauth_app_id)
    if oauth_app is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OAuth app not found")

    payload = payload or schemas.AuthorizationUrlRequest()
    requested_at = utcnow()
    if (
        oauth_app.authorization_state
        and oauth_app.authorization_state_expires_at is not None
        and oauth_app.authorization_state_expires_at >= requested_at
    ):
        _raise_oauth_conflict("OAUTH_FLOW_ALREADY_ACTIVE")
    if oauth_app.runtime_status == "healthy" and not payload.force_reauthorize:
        _raise_oauth_conflict("OAUTH_REAUTH_CONFIRMATION_REQUIRED")
    if payload.force_reauthorize and not (payload.reason or "").strip():
        _raise_oauth_conflict("OAUTH_REAUTH_REASON_REQUIRED")
    state = token_urlsafe(48)
    state_expires_at = requested_at + OAUTH_STATE_TTL

    claimed = db.execute(
        update(OAuthAppConfig)
        .where(
            OAuthAppConfig.id == oauth_app.id,
            or_(
                OAuthAppConfig.authorization_state.is_(None),
                OAuthAppConfig.authorization_state_expires_at.is_(None),
                OAuthAppConfig.authorization_state_expires_at < requested_at,
            ),
        )
        .values(
            authorization_status="authorization_requested",
            flow_status="requested",
            authorization_state=state,
            authorization_requested_at=requested_at,
            authorization_state_expires_at=state_expires_at,
            authorization_code_received_at=None,
            authorization_completed_at=None,
            authorization_error=None,
        )
    )
    if claimed.rowcount != 1:
        db.rollback()
        _raise_oauth_conflict("OAUTH_FLOW_ALREADY_ACTIVE")
    db.refresh(oauth_app)

    _record_event(db, oauth_app=oauth_app, event_type="authorization_requested")

    db.add(oauth_app)
    db.commit()
    db.refresh(oauth_app)

    query_params = {
            "client_id": oauth_app.client_id,
            "redirect_uri": oauth_app.redirect_uri,
            "response_type": "code",
            "scope": oauth_app.scopes,
            "state": state,
            "access_type": "offline",
            "include_granted_scopes": "true",
        }
    if oauth_app.active_credential_version is None or oauth_app.runtime_status == "revoked" or payload.force_reauthorize:
        query_params["prompt"] = "consent"
    query = urlencode(query_params)
    return schemas.AuthorizationUrlResponse(
        authorization_url=f"{GOOGLE_OAUTH_AUTHORIZATION_URL}?{query}",
        state=state,
        state_expires_at=state_expires_at,
    )


def _raise_oauth_conflict(code: str) -> None:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": code, "message": "OAuth authorization request is not allowed"},
    )


def handle_google_callback(db: Session, state: str, code: str) -> schemas.OAuthCallbackResponse:
    oauth_app = _consume_pending_oauth_app_state(db, state=state)
    return _exchange_authorization_code(db, oauth_app=oauth_app, code=code)


def import_google_callback_payload(
    db: Session,
    payload: schemas.OAuthCallbackImportRequest,
) -> schemas.OAuthCallbackResponse:
    oauth_app = _get_pending_oauth_app_by_state(db, state=payload.state)

    if payload.error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="callback returned error")
    if payload.iss and payload.iss != GOOGLE_OAUTH_ISSUER:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="issuer mismatch")
    if payload.redirect_uri.rstrip("/") != oauth_app.redirect_uri.rstrip("/"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="redirect_uri mismatch")

    parsed = urlparse(payload.callback_url)
    callback_uri = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
    if callback_uri != oauth_app.redirect_uri.rstrip("/"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="callback_url mismatch")

    query = parse_qs(parsed.query)
    callback_state = query.get("state", [None])[0]
    callback_code = query.get("code", [None])[0]
    if callback_state != payload.state:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="callback state mismatch")
    if callback_code != payload.code:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="callback code mismatch")

    oauth_app = _consume_pending_oauth_app_state(db, state=payload.state)
    return _exchange_authorization_code(db, oauth_app=oauth_app, code=payload.code)


def _get_pending_oauth_app_by_state(db: Session, *, state: str) -> OAuthAppConfig:
    oauth_app = db.scalar(select(OAuthAppConfig).where(OAuthAppConfig.authorization_state == state))
    if oauth_app is None:
        raise OAuthStateError

    now = utcnow()
    if oauth_app.authorization_state_expires_at is None or oauth_app.authorization_state_expires_at < now:
        raise OAuthStateError
    return oauth_app


def _consume_pending_oauth_app_state(db: Session, *, state: str) -> OAuthAppConfig:
    oauth_app = _get_pending_oauth_app_by_state(db, state=state)
    now = utcnow()
    consumed = db.execute(
        update(OAuthAppConfig)
        .where(
            OAuthAppConfig.id == oauth_app.id,
            OAuthAppConfig.authorization_state == state,
            OAuthAppConfig.authorization_state_expires_at.is_not(None),
            OAuthAppConfig.authorization_state_expires_at >= now,
        )
        .values(
            authorization_state=None,
            authorization_state_expires_at=None,
            authorization_code_received_at=now,
        )
    )
    if consumed.rowcount != 1:
        db.rollback()
        raise OAuthStateError
    db.commit()
    db.refresh(oauth_app)
    return oauth_app


def _exchange_authorization_code(
    db: Session,
    *,
    oauth_app: OAuthAppConfig,
    code: str,
) -> schemas.OAuthCallbackResponse:
    now = utcnow()

    try:
        response = requests.post(
            GOOGLE_OAUTH_TOKEN_URL,
            data={
                "code": code,
                "client_id": oauth_app.client_id,
                "client_secret": oauth_app.client_secret,
                "redirect_uri": oauth_app.redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=30,
        )
    except requests.RequestException as exc:
        oauth_app.authorization_status = "authorization_failed"
        oauth_app.flow_status = "exchange_failed"
        oauth_app.authorization_state = None
        oauth_app.authorization_state_expires_at = None
        oauth_app.authorization_error = "OAUTH_TOKEN_EXCHANGE_TRANSPORT"
        _record_event(
            db,
            oauth_app=oauth_app,
            event_type="token_exchange_failed",
            failure_class="oauth_transport",
        )
        db.add(oauth_app)
        db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="OAuth token exchange failed") from exc

    if response.status_code != status.HTTP_200_OK:
        oauth_app.authorization_status = "authorization_failed"
        oauth_app.flow_status = "exchange_failed"
        oauth_app.authorization_state = None
        oauth_app.authorization_state_expires_at = None
        oauth_app.authorization_error = "OAUTH_TOKEN_EXCHANGE_REJECTED"
        _record_event(
            db,
            oauth_app=oauth_app,
            event_type="token_exchange_failed",
            failure_class="oauth_exchange_rejected",
            http_status=response.status_code,
        )
        db.add(oauth_app)
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OAuth token exchange failed")

    token_payload = response.json()
    refresh_token = token_payload.get("refresh_token")
    if not refresh_token:
        oauth_app.authorization_status = "authorization_failed"
        oauth_app.flow_status = "exchange_failed"
        oauth_app.authorization_state = None
        oauth_app.authorization_state_expires_at = None
        oauth_app.authorization_error = "OAUTH_REFRESH_TOKEN_MISSING"
        _record_event(
            db,
            oauth_app=oauth_app,
            event_type="token_exchange_failed",
            failure_class="oauth_refresh_token_missing",
            http_status=response.status_code,
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "OAUTH_REFRESH_TOKEN_MISSING", "message": "Google did not return a refresh token"},
        )

    next_version = int(
        db.scalar(select(func.max(OAuthCredential.version)).where(OAuthCredential.oauth_app_id == oauth_app.id)) or 0
    ) + 1
    db.execute(
        update(OAuthCredential)
        .where(OAuthCredential.oauth_app_id == oauth_app.id, OAuthCredential.status == "staged")
        .values(status="rejected", retired_at=now)
    )
    cipher = _credential_cipher()
    staged = OAuthCredential(
        oauth_app_id=oauth_app.id,
        version=next_version,
        status="staged",
        client_secret_ciphertext=cipher.encrypt(oauth_app.client_secret),
        refresh_token_ciphertext=cipher.encrypt(str(refresh_token)),
        token_fingerprint=cipher.fingerprint(str(refresh_token)),
        granted_scopes=str(token_payload.get("scope") or oauth_app.scopes),
    )
    db.add(staged)

    oauth_app.authorization_status = "validation_pending"
    oauth_app.flow_status = "validation_pending"
    oauth_app.pending_credential_version = next_version
    oauth_app.authorization_state = None
    oauth_app.authorization_state_expires_at = None
    oauth_app.authorization_completed_at = None
    oauth_app.authorization_error = None
    oauth_app.access_token = None
    oauth_app.access_token_expires_at = None
    oauth_app.token_type = None
    oauth_app.granted_scopes = (
        str(token_payload.get("scope")) if token_payload.get("scope") is not None else oauth_app.scopes
    )
    _record_event(
        db,
        oauth_app=oauth_app,
        event_type="credential_staged",
        credential_version=next_version,
        http_status=response.status_code,
    )

    db.add(oauth_app)
    db.commit()
    db.refresh(oauth_app)

    return schemas.OAuthCallbackResponse(
        oauth_app_id=oauth_app.id,
        account_id=oauth_app.account_id,
        authorization_status=oauth_app.authorization_status,
        refresh_token_present=True,
    )


def _credential_cipher() -> CredentialCipher:
    settings = get_settings()
    return CredentialCipher(
        encryption_key=settings.credential_encryption_key,
        fingerprint_key=settings.credential_fingerprint_key,
    )


def _record_event(
    db: Session,
    *,
    oauth_app: OAuthAppConfig,
    event_type: str,
    credential_version: int | None = None,
    failure_class: str | None = None,
    http_status: int | None = None,
) -> None:
    db.add(
        OAuthEvent(
            account_id=oauth_app.account_id,
            oauth_app_id=oauth_app.id,
            event_type=event_type,
            credential_version=credential_version,
            failure_class=failure_class,
            http_status=http_status,
            metadata_json=json.dumps({"flow_status": oauth_app.flow_status}, separators=(",", ":")),
        )
    )
