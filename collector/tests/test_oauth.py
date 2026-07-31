from __future__ import annotations

import pytest

from app.oauth import refresh_access_token


class FakeResponse:
    def __init__(self, payload: dict[str, object], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict[str, object]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def post(self, url: str, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return self.response


def test_refresh_access_token_posts_expected_form_data() -> None:
    session = FakeSession(FakeResponse({"access_token": "access-token", "expires_in": 3600}))

    access_token = refresh_access_token(
        client_id="client-id",
        client_secret="client-secret",
        refresh_token="refresh-token",
        timeout_seconds=12,
        session=session,
    )

    assert access_token == "access-token"
    assert session.calls == [
        {
            "url": "https://oauth2.googleapis.com/token",
            "data": {
                "client_id": "client-id",
                "client_secret": "client-secret",
                "refresh_token": "refresh-token",
                "grant_type": "refresh_token",
            },
            "timeout": 12,
        }
    ]


def test_refresh_access_token_rejects_missing_access_token_field() -> None:
    session = FakeSession(FakeResponse({"token_type": "Bearer"}))

    with pytest.raises(ValueError, match="access_token"):
        refresh_access_token(
            client_id="client-id",
            client_secret="client-secret",
            refresh_token="refresh-token",
            session=session,
            timeout_seconds=12,
        )
