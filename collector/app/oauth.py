from __future__ import annotations

from typing import Any

import requests


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
    response.raise_for_status()
    payload = response.json()
    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise ValueError("OAuth token response did not include access_token")
    return access_token
