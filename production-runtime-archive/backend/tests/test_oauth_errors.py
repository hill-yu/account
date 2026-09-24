from __future__ import annotations

import pytest

from app.collectors.oauth_errors import (
    OAuthFailure,
    classify_oauth_error,
    oauth_contract_failure,
    oauth_transport_failure,
)


@pytest.mark.parametrize(
    ("grant_type", "error", "error_subtype", "expected_class"),
    [
        ("authorization_code", "invalid_grant", None, "oauth_code_invalid"),
        ("refresh_token", "invalid_grant", None, "oauth_refresh_revoked"),
        ("refresh_token", "invalid_grant", "invalid_rapt", "oauth_session_expired"),
        ("refresh_token", "invalid_client", None, "oauth_client_invalid"),
    ],
)
def test_classifies_google_oauth_failures(
    grant_type: str,
    error: str,
    error_subtype: str | None,
    expected_class: str,
) -> None:
    failure = classify_oauth_error(
        grant_type=grant_type,
        error=error,
        error_subtype=error_subtype,
        http_status=400,
    )

    assert failure.failure_class == expected_class
    assert failure.retryable is False
    assert failure.http_status == 400
    assert failure.error_subtype == error_subtype
    assert str(failure) == failure.public_message


@pytest.mark.parametrize(
    ("http_status", "expected_class"),
    [(429, "oauth_rate_limited"), (500, "oauth_provider_unavailable"), (503, "oauth_provider_unavailable")],
)
def test_classifies_retryable_http_failures(http_status: int, expected_class: str) -> None:
    failure = classify_oauth_error(
        grant_type="refresh_token",
        error="temporarily_unavailable",
        http_status=http_status,
    )

    assert failure.failure_class == expected_class
    assert failure.retryable is True


def test_transport_and_contract_failures_are_sanitized() -> None:
    timeout = oauth_transport_failure(timeout=True)
    contract = oauth_contract_failure(http_status=200)

    assert timeout.failure_class == "oauth_transport_timeout"
    assert timeout.retryable is True
    assert contract.failure_class == "oauth_response_invalid"
    assert contract.retryable is False
    assert "secret-token" not in repr(timeout)
    assert isinstance(timeout, OAuthFailure)

