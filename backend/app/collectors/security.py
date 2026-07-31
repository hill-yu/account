from __future__ import annotations

from hmac import compare_digest

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.config import get_settings
from app.models.collector_instance import CollectorInstance


bearer_scheme = HTTPBearer(auto_error=False)


def require_operator_authentication(request: Request) -> None:
    """Protect the operator namespace without changing collector or OAuth callback contracts."""
    if not request.url.path.startswith("/api/v1/operator/"):
        return
    expected_token = get_settings().operator_api_token
    supplied_token = request.headers.get("X-ADX-Operator-Token")
    if not expected_token or not supplied_token or not compare_digest(supplied_token, expected_token):
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
