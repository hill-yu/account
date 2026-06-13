from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.collector_instance import CollectorInstance


bearer_scheme = HTTPBearer(auto_error=False)


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
