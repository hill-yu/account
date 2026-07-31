from __future__ import annotations

from typing import Any

import requests

from app.oauth_errors import classify_oauth_error, oauth_contract_failure, oauth_transport_failure


GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"


def refresh_access_token(
    *,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    timeout_seconds: int = 30,
    session: requests.Session | Any | None = None,
) -> str:
    http = session or requests.Session()
    transport_failure = None
    try:
        response = http.post(
            GOOGLE_OAUTH_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=timeout_seconds,
        )
    except requests.Timeout:
        transport_failure = oauth_transport_failure(timeout=True)
    except requests.RequestException:
        transport_failure = oauth_transport_failure(timeout=False)
    if transport_failure is not None:
        raise transport_failure

    try:
        payload = response.json()
    except (TypeError, ValueError):
        raise oauth_contract_failure(http_status=response.status_code) from None
    if not isinstance(payload, dict):
        raise oauth_contract_failure(http_status=response.status_code)
    if response.status_code >= 400:
        error = payload.get("error")
        error_subtype = payload.get("error_subtype")
        raise classify_oauth_error(
            grant_type="refresh_token",
            error=error if isinstance(error, str) else None,
            error_subtype=error_subtype if isinstance(error_subtype, str) else None,
            http_status=response.status_code,
        )
    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise oauth_contract_failure(http_status=response.status_code)
    return access_token
