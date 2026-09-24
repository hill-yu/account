from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from binascii import Error as BinasciiError
from hashlib import sha256
from hmac import compare_digest, new
from time import time

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.config import get_settings
from app.models.collector_instance import CollectorInstance


bearer_scheme = HTTPBearer(auto_error=False)
OPERATOR_SESSION_COOKIE = "adx_operator_session"


def issue_operator_session() -> str:
    """Create a short-lived signed session without persisting operator credentials."""
    settings = get_settings()
    if not settings.operator_api_token:
        raise RuntimeError("ADX_COLLECTOR_OPERATOR_API_TOKEN is required to issue a session")
    now = int(time())
    payload = f"{now}.{now + settings.operator_session_ttl_seconds}".encode("ascii")
    encoded_payload = urlsafe_b64encode(payload).rstrip(b"=")
    signature = new(settings.operator_api_token.encode("utf-8"), encoded_payload, sha256).hexdigest().encode("ascii")
    return f"{encoded_payload.decode('ascii')}.{signature.decode('ascii')}"


def is_valid_operator_session(session_value: str | None) -> bool:
    settings = get_settings()
    if not settings.operator_api_token or not session_value:
        return False
    try:
        encoded_payload, supplied_signature = session_value.encode("ascii").rsplit(b".", 1)
        expected_signature = new(settings.operator_api_token.encode("utf-8"), encoded_payload, sha256).hexdigest().encode("ascii")
        padding = b"=" * (-len(encoded_payload) % 4)
        _issued_at, expires_at = urlsafe_b64decode(encoded_payload + padding).decode("ascii").split(".", 1)
        return compare_digest(supplied_signature, expected_signature) and int(expires_at) >= int(time())
    except (BinasciiError, UnicodeDecodeError, UnicodeEncodeError, ValueError):
        return False


def require_operator_authentication(request: Request) -> None:
    """Protect the operator namespace without changing collector or OAuth callback contracts."""
    if not request.url.path.startswith("/api/v1/operator/"):
        return
    expected_token = get_settings().operator_api_token
    supplied_token = request.headers.get("X-ADX-Operator-Token")
    supplied_session = request.cookies.get(OPERATOR_SESSION_COOKIE)
    has_legacy_token = bool(expected_token and supplied_token and compare_digest(supplied_token, expected_token))
    if not has_legacy_token and not is_valid_operator_session(supplied_session):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid operator token")


def get_authenticated_instance(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> CollectorInstance:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid collector token")

    instance = db.scalar(select(CollectorInstance).where(CollectorInstance.instance_token == credentials.credentials))
    if instance is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid collector token")

    return instance
