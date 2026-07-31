from __future__ import annotations

from datetime import date, datetime, timedelta
import json
from secrets import token_urlsafe
from urllib.parse import parse_qs, urlencode, urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
from fastapi import HTTPException, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.collectors import schemas, service
from app.collectors.credential_crypto import CredentialCipher
from app.collectors.oauth_errors import (
    OAuthFailure,
    classify_oauth_error,
    oauth_contract_failure,
    oauth_transport_failure,
)
from app.config import get_settings
from app.models.account import Account
from app.models.account_hourly_report import AccountHourlyReport
from app.models.collector_instance import CollectorInstance
from app.models.collector_sync_task import CollectorSyncTask
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


def list_oauth_apps(db: Session) -> list[schemas.OAuthAppRead]:
    oauth_apps = list(db.scalars(select(OAuthAppConfig).order_by(OAuthAppConfig.id)))
    credentials = list(
        db.scalars(
            select(OAuthCredential).where(OAuthCredential.status.in_(("active", "staged")))
        )
    )
    credentials_by_version = {
        (credential.oauth_app_id, credential.version): credential
        for credential in credentials
    }
    items: list[schemas.OAuthAppRead] = []
    for oauth_app in oauth_apps:
        visible_version = oauth_app.active_credential_version or oauth_app.pending_credential_version
        credential = credentials_by_version.get((oauth_app.id, visible_version)) if visible_version is not None else None
        fingerprint = credential.token_fingerprint if credential is not None else None
        item = schemas.OAuthAppRead.model_validate(oauth_app).model_copy(
            update={"credential_fingerprint": fingerprint[:12] if fingerprint else None}
        )
        items.append(item)
    return items


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=ZoneInfo("UTC"))
    return value.astimezone(ZoneInfo("UTC"))


def _latest_mature_report_date(*, now: datetime, timezone_name: str) -> date:
    candidate = now.astimezone(ZoneInfo(timezone_name)).date()
    while not service.is_authoritative_daily_ready(
        report_date=candidate,
        timezone_name=timezone_name,
        now=now,
    ):
        candidate -= timedelta(days=1)
    return candidate


def get_oauth_health_summary(db: Session) -> schemas.OAuthHealthSummary:
    """Build OAuth health metrics exclusively from control-plane tables."""
    now = _aware_utc(utcnow())
    runtime_counts = {
        str(runtime_status): int(account_count)
        for runtime_status, account_count in db.execute(
            select(OAuthAppConfig.runtime_status, func.count(OAuthAppConfig.id))
            .group_by(OAuthAppConfig.runtime_status)
            .order_by(OAuthAppConfig.runtime_status)
        )
    }
    failure_counts = {
        str(failure_class): int(failure_count or 0)
        for failure_class, failure_count in db.execute(
            select(OAuthAppConfig.failure_class, func.sum(OAuthAppConfig.failure_count))
            .where(OAuthAppConfig.failure_class.is_not(None))
            .group_by(OAuthAppConfig.failure_class)
            .order_by(OAuthAppConfig.failure_class)
        )
    }
    oauth_apps = list(db.scalars(select(OAuthAppConfig).order_by(OAuthAppConfig.account_id)))
    credentials = list(db.scalars(select(OAuthCredential)))
    credential_keys = {
        (credential.oauth_app_id, credential.version, credential.status)
        for credential in credentials
    }
    version_mismatch_total = sum(
        1
        for oauth_app in oauth_apps
        if (
            oauth_app.active_credential_version is not None
            and (oauth_app.id, oauth_app.active_credential_version, "active") not in credential_keys
        )
        or (
            oauth_app.pending_credential_version is not None
            and (oauth_app.id, oauth_app.pending_credential_version, "staged") not in credential_keys
        )
    )

    revoked_task_violations = 0
    for oauth_app in oauth_apps:
        if oauth_app.runtime_status != "revoked" or oauth_app.revoked_at is None:
            continue
        revoked_task_violations += int(
            db.scalar(
                select(func.count(CollectorSyncTask.id)).where(
                    CollectorSyncTask.account_id == oauth_app.account_id,
                    CollectorSyncTask.task_type.in_(("report_fetch", "report_fetch_hourly")),
                    CollectorSyncTask.created_at >= oauth_app.revoked_at,
                )
            )
            or 0
        )

    account_lags: list[schemas.OAuthAccountLag] = []
    accounts = list(
        db.scalars(
            select(Account)
            .join(OAuthAppConfig, OAuthAppConfig.account_id == Account.id)
            .order_by(Account.id)
        )
    )
    for account in accounts:
        latest_hourly = db.scalar(
            select(func.max(AccountHourlyReport.report_time_utc)).where(
                AccountHourlyReport.account_id == account.id
            )
        )
        hourly_lag = None
        if latest_hourly is not None:
            hourly_lag = round(max(0.0, (now - _aware_utc(latest_hourly)).total_seconds() / 3600), 2)
        latest_authoritative = db.scalar(
            select(func.max(CollectorSyncTask.report_date)).where(
                CollectorSyncTask.account_id == account.id,
                CollectorSyncTask.task_type == "report_fetch",
                CollectorSyncTask.status == "succeeded",
            )
        )
        timezone_name = account.timezone or service.DEFAULT_REPORT_TIMEZONE
        latest_mature = _latest_mature_report_date(now=now, timezone_name=timezone_name)
        if latest_authoritative is not None and latest_authoritative >= latest_mature:
            daily_lag = 0.0
        else:
            first_missing = latest_authoritative + timedelta(days=1) if latest_authoritative else latest_mature
            ready_at = service.authoritative_daily_ready_at(
                report_date=first_missing,
                timezone_name=timezone_name,
            )
            daily_lag = round(max(0.0, (now - ready_at).total_seconds() / 3600), 2)
        account_lags.append(
            schemas.OAuthAccountLag(
                account_id=account.id,
                account_name=account.name,
                timezone=timezone_name,
                latest_hourly_watermark_utc=latest_hourly,
                hourly_watermark_lag_hours=hourly_lag,
                latest_authoritative_report_date=latest_authoritative,
                authoritative_daily_lag_hours=daily_lag,
            )
        )
    return schemas.OAuthHealthSummary(
        generated_at=now,
        oauth_runtime_status_accounts=runtime_counts,
        oauth_refresh_failure_total=failure_counts,
        oauth_credential_version_mismatch_total=version_mismatch_total,
        revoked_account_task_created_total=revoked_task_violations,
        account_lags=account_lags,
    )


def create_oauth_app(db: Session, payload: schemas.OAuthAppCreate) -> OAuthAppConfig:
    account = db.get(Account, payload.account_id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    cipher = _credential_cipher()
    oauth_app = OAuthAppConfig(
        account_id=payload.account_id,
        client_id=payload.client_id,
        client_secret="",
        redirect_uri=payload.redirect_uri,
        scopes=payload.scopes,
        app_status=payload.app_status,
        verification_status=payload.verification_status,
    )
    db.add(oauth_app)
    db.flush()
    oauth_app.pending_credential_version = 1
    db.add(
        OAuthCredential(
            oauth_app_id=oauth_app.id,
            version=1,
            status="staged",
            client_secret_ciphertext=cipher.encrypt(payload.client_secret),
            refresh_token_ciphertext=None,
            token_fingerprint=None,
        )
    )
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
    if oauth_app.flow_status in {"exchanging", "validation_pending"}:
        _raise_oauth_conflict("OAUTH_FLOW_ALREADY_ACTIVE")
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
            OAuthAppConfig.flow_status.notin_(("exchanging", "validation_pending")),
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


def _resolve_oauth_client_secret(
    db: Session,
    *,
    oauth_app: OAuthAppConfig,
    cipher: CredentialCipher,
) -> str:
    if oauth_app.client_secret:
        return oauth_app.client_secret
    credential_version = oauth_app.active_credential_version or oauth_app.pending_credential_version
    if credential_version is None:
        latest = db.scalar(
            select(OAuthCredential)
            .where(OAuthCredential.oauth_app_id == oauth_app.id)
            .order_by(OAuthCredential.version.desc())
        )
        if latest is None:
            _raise_oauth_conflict("OAUTH_CLIENT_SECRET_UNAVAILABLE")
        return cipher.decrypt(latest.client_secret_ciphertext)
    credential = db.scalar(
        select(OAuthCredential).where(
            OAuthCredential.oauth_app_id == oauth_app.id,
            OAuthCredential.version == credential_version,
            OAuthCredential.status.in_(("active", "staged")),
        )
    )
    if credential is None:
        _raise_oauth_conflict("OAUTH_CLIENT_SECRET_UNAVAILABLE")
    return cipher.decrypt(credential.client_secret_ciphertext)


def handle_google_callback(
    db: Session,
    state: str,
    code: str,
    issuer: str | None,
) -> schemas.OAuthCallbackResponse:
    if issuer != GOOGLE_OAUTH_ISSUER:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="issuer mismatch")
    oauth_app = _consume_pending_oauth_app_state(db, state=state)
    return _exchange_authorization_code(db, oauth_app=oauth_app, code=code)


def import_google_callback_payload(
    db: Session,
    payload: schemas.OAuthCallbackImportRequest,
) -> schemas.OAuthCallbackResponse:
    oauth_app = _get_pending_oauth_app_by_state(db, state=payload.state)

    if payload.error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="callback returned error")
    if payload.iss != GOOGLE_OAUTH_ISSUER:
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
            flow_status="exchanging",
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
    cipher = _credential_cipher()
    client_secret = _resolve_oauth_client_secret(db, oauth_app=oauth_app, cipher=cipher)

    try:
        response = requests.post(
            GOOGLE_OAUTH_TOKEN_URL,
            data={
                "code": code,
                "client_id": oauth_app.client_id,
                "client_secret": client_secret,
                "redirect_uri": oauth_app.redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=30,
        )
    except requests.RequestException as exc:
        failure = oauth_transport_failure(timeout=isinstance(exc, requests.Timeout))
        _persist_exchange_failure(db, oauth_app=oauth_app, failure=failure)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="OAuth token exchange failed") from None

    if response.status_code != status.HTTP_200_OK:
        try:
            error_payload = response.json()
        except (TypeError, ValueError):
            error_payload = {}
        error = error_payload.get("error") if isinstance(error_payload, dict) else None
        error_subtype = error_payload.get("error_subtype") if isinstance(error_payload, dict) else None
        failure = classify_oauth_error(
            grant_type="authorization_code",
            error=error if isinstance(error, str) else None,
            error_subtype=error_subtype if isinstance(error_subtype, str) else None,
            http_status=response.status_code,
        )
        _persist_exchange_failure(db, oauth_app=oauth_app, failure=failure)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OAuth token exchange failed")

    try:
        token_payload = response.json()
    except (TypeError, ValueError):
        failure = oauth_contract_failure(http_status=response.status_code)
        _persist_exchange_failure(db, oauth_app=oauth_app, failure=failure)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="OAuth token exchange failed") from None
    if not isinstance(token_payload, dict):
        failure = oauth_contract_failure(http_status=response.status_code)
        _persist_exchange_failure(db, oauth_app=oauth_app, failure=failure)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="OAuth token exchange failed")
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

    staged = db.scalar(
        select(OAuthCredential).where(
            OAuthCredential.oauth_app_id == oauth_app.id,
            OAuthCredential.status == "staged",
        )
    )
    if staged is not None and staged.refresh_token_ciphertext is None:
        next_version = staged.version
        staged.refresh_token_ciphertext = cipher.encrypt(str(refresh_token))
        staged.token_fingerprint = cipher.fingerprint(str(refresh_token))
        staged.granted_scopes = str(token_payload.get("scope") or oauth_app.scopes)
    else:
        next_version = int(
            db.scalar(select(func.max(OAuthCredential.version)).where(OAuthCredential.oauth_app_id == oauth_app.id)) or 0
        ) + 1
        db.execute(
            update(OAuthCredential)
            .where(OAuthCredential.oauth_app_id == oauth_app.id, OAuthCredential.status == "staged")
            .values(status="rejected", retired_at=now)
        )
        staged = OAuthCredential(
            oauth_app_id=oauth_app.id,
            version=next_version,
            status="staged",
            client_secret_ciphertext=cipher.encrypt(client_secret),
            refresh_token_ciphertext=cipher.encrypt(str(refresh_token)),
            token_fingerprint=cipher.fingerprint(str(refresh_token)),
            granted_scopes=str(token_payload.get("scope") or oauth_app.scopes),
        )
        db.add(staged)

    instance = db.scalar(select(CollectorInstance).where(CollectorInstance.account_id == oauth_app.account_id))
    if instance is not None:
        db.add(
            CollectorSyncTask(
                account_id=oauth_app.account_id,
                collector_instance_id=instance.id,
                task_type="oauth_credential_validate",
                report_date=now.date(),
                status="pending",
                external_request_id=f"oauth-validate-{oauth_app.id}-v{next_version}",
            )
        )

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


def acknowledge_credential_validation(
    db: Session,
    *,
    instance: CollectorInstance,
    payload: schemas.OAuthCredentialAckRequest,
) -> schemas.OAuthCredentialAckResponse:
    if payload.account_id != instance.account_id:
        _raise_stale_credential_ack()
    oauth_app = db.scalar(select(OAuthAppConfig).where(OAuthAppConfig.account_id == instance.account_id))
    account = db.get(Account, instance.account_id)
    task = db.get(CollectorSyncTask, payload.task_id)
    if (
        oauth_app is None
        or account is None
        or task is None
        or task.account_id != instance.account_id
        or task.collector_instance_id != instance.id
        or task.task_type != "oauth_credential_validate"
        or task.status != "in_progress"
        or oauth_app.flow_status != "validation_pending"
        or oauth_app.pending_credential_version != payload.credential_version
        or account.external_account_id != payload.network_code
    ):
        _raise_stale_credential_ack()

    service.assert_fetch_allowed(
        db,
        account_id=instance.account_id,
        fetch_kind="oauth_credential_validate",
        credential_version=payload.credential_version,
    )
    staged = db.scalar(
        select(OAuthCredential).where(
            OAuthCredential.oauth_app_id == oauth_app.id,
            OAuthCredential.version == payload.credential_version,
            OAuthCredential.status == "staged",
        )
    )
    if staged is None or staged.token_fingerprint != payload.token_fingerprint:
        _raise_stale_credential_ack()
    try:
        network_zone = ZoneInfo(payload.network_timezone)
    except ZoneInfoNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "OAUTH_NETWORK_TIMEZONE_INVALID", "message": "Network timezone is invalid"},
        ) from None

    now = utcnow()
    db.execute(
        update(OAuthCredential)
        .where(OAuthCredential.oauth_app_id == oauth_app.id, OAuthCredential.status == "active")
        .values(status="retired", retired_at=now)
    )
    db.flush()
    staged.status = "active"
    staged.validated_at = now
    staged.activated_at = now
    staged.granted_scopes = payload.granted_scopes
    oauth_app.active_credential_version = payload.credential_version
    oauth_app.pending_credential_version = None
    oauth_app.flow_status = "completed"
    oauth_app.authorization_status = "authorized"
    oauth_app.runtime_status = "degraded"
    oauth_app.last_verified_at = now
    oauth_app.failure_class = None
    oauth_app.failure_count = 0
    oauth_app.next_action = "run_oauth_health_check"
    oauth_app.client_secret = ""
    oauth_app.refresh_token = None
    oauth_app.refresh_token_updated_at = None
    oauth_app.access_token = None
    oauth_app.access_token_expires_at = None
    oauth_app.token_type = None
    account.timezone = payload.network_timezone
    task.status = "succeeded"
    task.finished_at = now
    health_report_date = datetime.now(network_zone).date() - timedelta(days=2)
    health_task = CollectorSyncTask(
        account_id=account.id,
        collector_instance_id=instance.id,
        task_type="oauth_health_check",
        report_date=health_report_date,
        status="pending",
        external_request_id=f"oauth-health-{oauth_app.id}-v{payload.credential_version}",
    )
    db.add_all([staged, oauth_app, account, task, health_task])
    _record_event(
        db,
        oauth_app=oauth_app,
        event_type="credential_activated",
        credential_version=payload.credential_version,
    )
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(health_task)
    return schemas.OAuthCredentialAckResponse(
        account_id=account.id,
        credential_version=payload.credential_version,
        status="activated",
        health_task_id=health_task.id,
    )


def _raise_stale_credential_ack() -> None:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": "STALE_CREDENTIAL_ACK", "message": "Credential acknowledgement is stale or invalid"},
    )


def _persist_exchange_failure(
    db: Session,
    *,
    oauth_app: OAuthAppConfig,
    failure: OAuthFailure,
) -> None:
    oauth_app.authorization_status = "authorization_failed"
    oauth_app.flow_status = "exchange_failed"
    oauth_app.authorization_state = None
    oauth_app.authorization_state_expires_at = None
    oauth_app.authorization_error = failure.failure_class
    _record_event(
        db,
        oauth_app=oauth_app,
        event_type="token_exchange_failed",
        failure_class=failure.failure_class,
        http_status=failure.http_status,
    )
    db.add(oauth_app)
    db.commit()


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
