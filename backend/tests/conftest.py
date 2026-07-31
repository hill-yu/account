from __future__ import annotations

from collections.abc import Callable

import pytest
from cryptography.fernet import Fernet

from app.models.collector_account_policy import CollectorAccountPolicy
from app.models.oauth_credential import OAuthCredential
from app.models.oauth_event import OAuthEvent


@pytest.fixture(autouse=True)
def bypass_fetch_policy_for_legacy_tests(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if request.module.__name__.endswith("test_fetch_policy"):
        return

    from app.collectors import service

    monkeypatch.setattr(service, "assert_fetch_allowed", lambda *args, **kwargs: None)


@pytest.fixture()
def credential_encryption_key() -> str:
    return Fernet.generate_key().decode("ascii")


@pytest.fixture()
def credential_fingerprint_key() -> str:
    return "test-only-fingerprint-key-with-sufficient-entropy"


@pytest.fixture()
def oauth_credential_factory() -> Callable[..., OAuthCredential]:
    def factory(*, oauth_app_id: int, version: int = 1, status: str = "active") -> OAuthCredential:
        return OAuthCredential(
            oauth_app_id=oauth_app_id,
            version=version,
            status=status,
            client_secret_ciphertext=f"encrypted-client-secret-{version}",
            refresh_token_ciphertext=f"encrypted-refresh-token-{version}",
            token_fingerprint=f"fingerprint-{version}",
            granted_scopes="https://www.googleapis.com/auth/admanager",
        )

    return factory


@pytest.fixture()
def collector_policy_factory() -> Callable[..., CollectorAccountPolicy]:
    def factory(*, account_id: int, **overrides: object) -> CollectorAccountPolicy:
        values: dict[str, object] = {
            "account_id": account_id,
            "lifecycle_status": "active",
            "gray_enabled": True,
            "hourly_fetch_enabled": True,
            "authoritative_daily_enabled": True,
            "manual_fetch_enabled": True,
        }
        values.update(overrides)
        return CollectorAccountPolicy(**values)

    return factory


@pytest.fixture()
def oauth_event_factory() -> Callable[..., OAuthEvent]:
    def factory(*, account_id: int, oauth_app_id: int, **overrides: object) -> OAuthEvent:
        values: dict[str, object] = {
            "account_id": account_id,
            "oauth_app_id": oauth_app_id,
            "event_type": "credential_tested",
        }
        values.update(overrides)
        return OAuthEvent(**values)

    return factory
