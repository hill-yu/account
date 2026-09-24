from __future__ import annotations

import pytest
import requests

from app.oauth import refresh_access_token
from app.oauth_errors import OAuthFailure


class FakeResponse:
    def __init__(
        self,
        payload: dict[str, object],
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}

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


class RaisingSession:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def post(self, url: str, **kwargs):
        raise self.error


class SequenceSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = iter(responses)
        self.calls = 0

    def post(self, url: str, **kwargs):
        del url, kwargs
        self.calls += 1
        return next(self.responses)


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

    with pytest.raises(OAuthFailure) as exc_info:
        refresh_access_token(
            client_id="client-id",
            client_secret="client-secret",
            refresh_token="refresh-token",
            session=session,
            timeout_seconds=12,
        )

    assert exc_info.value.failure_class == "oauth_response_invalid"
    assert exc_info.value.retryable is False


@pytest.mark.parametrize(
    ("payload", "status_code", "expected_class", "retryable"),
    [
        ({"error": "invalid_grant"}, 400, "oauth_refresh_revoked", False),
        ({"error": "invalid_grant", "error_subtype": "invalid_rapt"}, 400, "oauth_session_expired", False),
        ({"error": "invalid_client"}, 400, "oauth_client_invalid", False),
        ({"error": "rate_limit"}, 429, "oauth_rate_limited", True),
        ({"error": "temporarily_unavailable"}, 503, "oauth_provider_unavailable", True),
    ],
)
def test_refresh_access_token_raises_structured_failure(
    payload: dict[str, object],
    status_code: int,
    expected_class: str,
    retryable: bool,
) -> None:
    session = FakeSession(FakeResponse(payload, status_code=status_code))

    with pytest.raises(OAuthFailure) as exc_info:
        refresh_access_token(
            client_id="client-id",
            client_secret="client-secret",
            refresh_token="secret-refresh-token",
            session=session,
            max_attempts=1,
        )

    failure = exc_info.value
    assert failure.failure_class == expected_class
    assert failure.retryable is retryable
    assert failure.http_status == status_code
    assert "secret-refresh-token" not in str(failure)
    assert "secret-refresh-token" not in repr(failure)


def test_refresh_access_token_honors_retry_after_before_success() -> None:
    session = SequenceSession(
        [
            FakeResponse({"error": "rate_limit"}, status_code=429, headers={"Retry-After": "2"}),
            FakeResponse({"access_token": "recovered-access-token"}),
        ]
    )
    waits: list[float] = []

    access_token = refresh_access_token(
        client_id="client-id",
        client_secret="client-secret",
        refresh_token="refresh-token",
        session=session,
        sleep=waits.append,
        max_attempts=3,
    )

    assert access_token == "recovered-access-token"
    assert session.calls == 2
    assert waits == [2.0]


def test_refresh_access_token_bounds_provider_retries() -> None:
    session = SequenceSession(
        [FakeResponse({"error": "temporarily_unavailable"}, status_code=503) for _ in range(3)]
    )
    waits: list[float] = []

    with pytest.raises(OAuthFailure) as exc_info:
        refresh_access_token(
            client_id="client-id",
            client_secret="client-secret",
            refresh_token="refresh-token",
            session=session,
            sleep=waits.append,
            max_attempts=3,
        )

    assert exc_info.value.failure_class == "oauth_provider_unavailable"
    assert session.calls == 3
    assert waits == [1.0, 2.0]


def test_refresh_access_token_classifies_timeout_without_leaking_exception() -> None:
    session = RaisingSession(requests.Timeout("request contained secret-refresh-token"))

    with pytest.raises(OAuthFailure) as exc_info:
        refresh_access_token(
            client_id="client-id",
            client_secret="client-secret",
            refresh_token="secret-refresh-token",
            session=session,
        )

    assert exc_info.value.failure_class == "oauth_transport_timeout"
    assert exc_info.value.retryable is True
    assert "secret-refresh-token" not in repr(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
