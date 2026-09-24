from __future__ import annotations


_PUBLIC_MESSAGES = {
    "oauth_code_invalid": "OAuth authorization code is invalid or expired",
    "oauth_refresh_revoked": "OAuth refresh credential is no longer valid",
    "oauth_session_expired": "OAuth account session requires reauthorization",
    "oauth_client_invalid": "OAuth client configuration was rejected",
    "oauth_rate_limited": "OAuth provider rate limit was reached",
    "oauth_provider_unavailable": "OAuth provider is temporarily unavailable",
    "oauth_transport_timeout": "OAuth provider request timed out",
    "oauth_transport_error": "OAuth provider could not be reached",
    "oauth_response_invalid": "OAuth provider returned an invalid response",
    "oauth_request_rejected": "OAuth provider rejected the request",
}


class OAuthFailure(Exception):
    def __init__(
        self,
        *,
        failure_class: str,
        retryable: bool,
        http_status: int | None = None,
        error_subtype: str | None = None,
    ) -> None:
        self.failure_class = failure_class
        self.retryable = retryable
        self.http_status = http_status
        self.error_subtype = error_subtype
        self.public_message = _PUBLIC_MESSAGES[failure_class]
        super().__init__(self.public_message)

    def __repr__(self) -> str:
        return (
            "OAuthFailure("
            f"failure_class={self.failure_class!r}, retryable={self.retryable!r}, "
            f"http_status={self.http_status!r}, error_subtype={self.error_subtype!r})"
        )


def classify_oauth_error(
    *,
    grant_type: str,
    error: str | None,
    error_subtype: str | None = None,
    http_status: int | None = None,
) -> OAuthFailure:
    safe_subtype = error_subtype if error_subtype == "invalid_rapt" else None
    if http_status == 429:
        return OAuthFailure(failure_class="oauth_rate_limited", retryable=True, http_status=http_status)
    if http_status is not None and http_status >= 500:
        return OAuthFailure(failure_class="oauth_provider_unavailable", retryable=True, http_status=http_status)
    if error == "invalid_grant" and grant_type == "authorization_code":
        failure_class = "oauth_code_invalid"
    elif error == "invalid_grant" and safe_subtype == "invalid_rapt":
        failure_class = "oauth_session_expired"
    elif error == "invalid_grant" and grant_type == "refresh_token":
        failure_class = "oauth_refresh_revoked"
    elif error == "invalid_client":
        failure_class = "oauth_client_invalid"
    elif error == "temporarily_unavailable":
        return OAuthFailure(
            failure_class="oauth_provider_unavailable",
            retryable=True,
            http_status=http_status,
            error_subtype=safe_subtype,
        )
    else:
        failure_class = "oauth_request_rejected"
    return OAuthFailure(
        failure_class=failure_class,
        retryable=False,
        http_status=http_status,
        error_subtype=safe_subtype,
    )


def oauth_transport_failure(*, timeout: bool, http_status: int | None = None) -> OAuthFailure:
    return OAuthFailure(
        failure_class="oauth_transport_timeout" if timeout else "oauth_transport_error",
        retryable=True,
        http_status=http_status,
    )


def oauth_contract_failure(*, http_status: int | None = None) -> OAuthFailure:
    return OAuthFailure(
        failure_class="oauth_response_invalid",
        retryable=False,
        http_status=http_status,
    )
