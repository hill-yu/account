from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests

from app.admanager_soap import AdManagerSoapClient
from app.models import RuntimeSettings
from app.oauth import OAuthTokenResponse, refresh_access_token_metadata
from app.oauth_errors import oauth_contract_failure
from app.proxy import ProxyConfig


AD_MANAGER_SCOPE = "https://www.googleapis.com/auth/admanager"


@dataclass(frozen=True)
class OAuthValidationResult:
    account_id: int | None
    credential_version: int
    token_fingerprint: str
    network_code: str
    network_timezone: str
    granted_scopes: str


class OAuthCredentialValidator:
    def __init__(
        self,
        *,
        settings: RuntimeSettings,
        account_id: int | None = None,
        token_refresher: Callable[..., OAuthTokenResponse] = refresh_access_token_metadata,
        network_client_factory: Callable[..., AdManagerSoapClient] = AdManagerSoapClient,
    ) -> None:
        self._settings = settings
        self._account_id = account_id
        self._token_refresher = token_refresher
        self._network_client_factory = network_client_factory

    def validate(self) -> OAuthValidationResult:
        settings = self._settings
        required = {
            "credential_version": settings.credential_version,
            "credential_fingerprint": settings.credential_fingerprint,
            "network_code": settings.admanager_network_code,
            "client_id": settings.google_oauth_client_id,
            "client_secret": settings.google_oauth_client_secret,
            "refresh_token": settings.google_oauth_refresh_token,
        }
        if any(value is None or value == "" for value in required.values()):
            raise oauth_contract_failure()
        proxy = ProxyConfig(
            protocol=settings.proxy_protocol,
            host=settings.proxy_host,
            port=settings.proxy_port,
            username=settings.proxy_username,
            password=settings.proxy_password,
            expected_egress_ip=settings.expected_egress_ip,
        )
        session = requests.Session()
        session.proxies.update(proxy.as_requests_proxies())
        token = self._token_refresher(
            client_id=settings.google_oauth_client_id,
            client_secret=settings.google_oauth_client_secret,
            refresh_token=settings.google_oauth_refresh_token,
            timeout_seconds=settings.request_timeout_seconds,
            session=session,
        )
        if token.token_type is not None and token.token_type.lower() != "bearer":
            raise oauth_contract_failure(http_status=200)
        granted_scopes = token.scope or settings.granted_scopes or ""
        if AD_MANAGER_SCOPE not in granted_scopes.split():
            raise oauth_contract_failure(http_status=200)
        network_client = self._network_client_factory(
            network_code=settings.admanager_network_code,
            client_id=settings.google_oauth_client_id,
            client_secret=settings.google_oauth_client_secret,
            refresh_token=settings.google_oauth_refresh_token,
            timeout_seconds=settings.request_timeout_seconds,
            proxy_config=proxy,
        )
        network = network_client.fetch_current_network()
        if network["network_code"] != settings.admanager_network_code:
            raise oauth_contract_failure(http_status=200)
        try:
            ZoneInfo(network["timezone"])
        except (KeyError, ZoneInfoNotFoundError):
            raise oauth_contract_failure(http_status=200) from None
        return OAuthValidationResult(
            account_id=self._account_id,
            credential_version=int(settings.credential_version),
            token_fingerprint=str(settings.credential_fingerprint),
            network_code=network["network_code"],
            network_timezone=network["timezone"],
            granted_scopes=granted_scopes,
        )
