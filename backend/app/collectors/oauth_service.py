from __future__ import annotations

from datetime import datetime, timedelta
from secrets import token_urlsafe
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collectors import schemas, service
from app.models.account import Account
from app.models.oauth_app_config import OAuthAppConfig


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


def generate_authorization_url(db: Session, oauth_app_id: int) -> schemas.AuthorizationUrlResponse:
    oauth_app = db.get(OAuthAppConfig, oauth_app_id)
    if oauth_app is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OAuth app not found")

    requested_at = utcnow()
    state = token_urlsafe(48)
    state_expires_at = requested_at + OAUTH_STATE_TTL

    oauth_app.authorization_status = "authorization_requested"
    oauth_app.authorization_state = state
    oauth_app.authorization_requested_at = requested_at
    oauth_app.authorization_state_expires_at = state_expires_at
    oauth_app.authorization_code_received_at = None
    oauth_app.authorization_completed_at = None
    oauth_app.authorization_error = None

    db.add(oauth_app)
    db.commit()
    db.refresh(oauth_app)

    query = urlencode(
        {
            "client_id": oauth_app.client_id,
            "redirect_uri": oauth_app.redirect_uri,
            "response_type": "code",
            "scope": oauth_app.scopes,
            "state": state,
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",
        }
    )
    return schemas.AuthorizationUrlResponse(
        authorization_url=f"{GOOGLE_OAUTH_AUTHORIZATION_URL}?{query}",
        state=state,
        state_expires_at=state_expires_at,
    )


def handle_google_callback(db: Session, state: str, code: str) -> schemas.OAuthCallbackResponse:
    oauth_app = _get_pending_oauth_app_by_state(db, state=state)
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

    return _exchange_authorization_code(db, oauth_app=oauth_app, code=payload.code)


def _get_pending_oauth_app_by_state(db: Session, *, state: str) -> OAuthAppConfig:
    oauth_app = db.scalar(select(OAuthAppConfig).where(OAuthAppConfig.authorization_state == state))
    if oauth_app is None:
        raise OAuthStateError

    now = utcnow()
    if oauth_app.authorization_state_expires_at is None or oauth_app.authorization_state_expires_at < now:
        raise OAuthStateError
    return oauth_app


def _exchange_authorization_code(
    db: Session,
    *,
    oauth_app: OAuthAppConfig,
    code: str,
) -> schemas.OAuthCallbackResponse:
    now = utcnow()
    oauth_app.authorization_code_received_at = now

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
        oauth_app.authorization_error = str(exc)
        db.add(oauth_app)
        db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="OAuth token exchange failed") from exc

    if response.status_code != status.HTTP_200_OK:
        oauth_app.authorization_status = "authorization_failed"
        oauth_app.authorization_error = response.text[:500]
        db.add(oauth_app)
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OAuth token exchange failed")

    token_payload = response.json()
    expires_in = token_payload.get("expires_in")
    access_token_expires_at = now + timedelta(seconds=int(expires_in)) if expires_in is not None else None
    refresh_token = token_payload.get("refresh_token") or oauth_app.refresh_token

    oauth_app.authorization_status = "authorized"
    oauth_app.authorization_state = None
    oauth_app.authorization_state_expires_at = None
    oauth_app.authorization_completed_at = now
    oauth_app.authorization_error = None
    oauth_app.access_token = str(token_payload["access_token"])
    oauth_app.access_token_expires_at = access_token_expires_at
    oauth_app.refresh_token = str(refresh_token) if refresh_token is not None else None
    oauth_app.refresh_token_updated_at = now if token_payload.get("refresh_token") else oauth_app.refresh_token_updated_at
    oauth_app.token_type = str(token_payload.get("token_type")) if token_payload.get("token_type") is not None else None
    oauth_app.granted_scopes = (
        str(token_payload.get("scope")) if token_payload.get("scope") is not None else oauth_app.scopes
    )

    db.add(oauth_app)
    db.commit()
    db.refresh(oauth_app)

    return schemas.OAuthCallbackResponse(
        oauth_app_id=oauth_app.id,
        account_id=oauth_app.account_id,
        authorization_status=oauth_app.authorization_status,
        refresh_token_present=oauth_app.refresh_token_present,
    )
