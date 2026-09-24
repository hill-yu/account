from __future__ import annotations

from app.models import RuntimeSettings
from app.oauth import OAuthTokenResponse
from app.oauth_errors import OAuthFailure
from app.oauth_validation import AD_MANAGER_SCOPE, OAuthCredentialValidator


def validation_settings() -> RuntimeSettings:
    return RuntimeSettings(
        control_plane_base_url="https://control.example.com",
        instance_token="instance-token",
        proxy_protocol="socks5",
        proxy_host="proxy.example.com",
        proxy_port=5001,
        proxy_username="proxy-user",
        proxy_password="proxy-password",
        expected_egress_ip="203.0.113.10",
        fetch_mode="admanager_soap",
        operation="oauth_credential_validate",
        credential_version=2,
        credential_fingerprint="fingerprint-v2",
        granted_scopes=AD_MANAGER_SCOPE,
        admanager_network_code="network-123",
        google_oauth_client_id="client-id",
        google_oauth_client_secret="client-secret",
        google_oauth_refresh_token="refresh-token",
    )


def test_validates_refresh_scope_network_code_and_timezone_in_order() -> None:
    calls: list[str] = []

    def refresh(**kwargs):
        calls.append("refresh")
        assert kwargs["session"].proxies["https"].startswith("socks5://proxy-user:proxy-password@")
        return OAuthTokenResponse(access_token="memory-only", token_type="Bearer", scope=AD_MANAGER_SCOPE)

    class NetworkClient:
        def fetch_current_network(self):
            calls.append("network")
            return {"network_code": "network-123", "timezone": "America/Los_Angeles"}

    validator = OAuthCredentialValidator(
        settings=validation_settings(),
        account_id=7,
        token_refresher=refresh,
        network_client_factory=lambda **kwargs: NetworkClient(),
    )

    result = validator.validate()

    assert calls == ["refresh", "network"]
    assert result.account_id == 7
    assert result.credential_version == 2
    assert result.token_fingerprint == "fingerprint-v2"
    assert result.network_code == "network-123"
    assert result.network_timezone == "America/Los_Angeles"
    assert result.granted_scopes == AD_MANAGER_SCOPE
    assert "memory-only" not in repr(result)


def test_rejects_scope_before_calling_network_service() -> None:
    network_called = False

    def refresh(**kwargs):
        return OAuthTokenResponse(access_token="memory-only", token_type="Bearer", scope="openid")

    def network_factory(**kwargs):
        nonlocal network_called
        network_called = True
        raise AssertionError("network must not be called")

    validator = OAuthCredentialValidator(
        settings=validation_settings(),
        token_refresher=refresh,
        network_client_factory=network_factory,
    )

    try:
        validator.validate()
    except OAuthFailure as exc:
        assert exc.failure_class == "oauth_response_invalid"
    else:
        raise AssertionError("validation should fail")
    assert network_called is False


def test_rejects_network_code_mismatch() -> None:
    class WrongNetworkClient:
        def fetch_current_network(self):
            return {"network_code": "different-network", "timezone": "America/Los_Angeles"}

    validator = OAuthCredentialValidator(
        settings=validation_settings(),
        token_refresher=lambda **kwargs: OAuthTokenResponse(
            access_token="memory-only",
            token_type="Bearer",
            scope=AD_MANAGER_SCOPE,
        ),
        network_client_factory=lambda **kwargs: WrongNetworkClient(),
    )

    try:
        validator.validate()
    except OAuthFailure as exc:
        assert exc.failure_class == "oauth_response_invalid"
    else:
        raise AssertionError("validation should fail")
