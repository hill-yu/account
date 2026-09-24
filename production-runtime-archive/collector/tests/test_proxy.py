from __future__ import annotations

import pytest

from app.proxy import ProxyConfig, ProxyConfigError


def test_proxy_config_builds_requests_mapping() -> None:
    config = ProxyConfig(
        protocol="http",
        host="proxy.example.com",
        port=8080,
        username="proxy-user",
        password="proxy-pass",
        expected_egress_ip="203.0.113.10",
    )

    assert config.as_requests_proxies() == {
        "http": "http://proxy-user:proxy-pass@proxy.example.com:8080",
        "https": "http://proxy-user:proxy-pass@proxy.example.com:8080",
    }


def test_proxy_config_rejects_partial_credentials() -> None:
    with pytest.raises(ProxyConfigError, match="both username and password"):
        ProxyConfig(
            protocol="http",
            host="proxy.example.com",
            port=8080,
            username="proxy-user",
            password=None,
            expected_egress_ip="203.0.113.10",
        )


def test_proxy_config_rejects_invalid_port() -> None:
    with pytest.raises(ProxyConfigError, match="port"):
        ProxyConfig(
            protocol="http",
            host="proxy.example.com",
            port=0,
            username=None,
            password=None,
            expected_egress_ip="203.0.113.10",
        )


def test_proxy_config_encodes_reserved_characters_in_credentials() -> None:
    config = ProxyConfig(
        protocol="http",
        host="proxy.example.com",
        port=8080,
        username="user/name",
        password="pa:ss/word",
        expected_egress_ip="203.0.113.10",
    )

    assert config.as_requests_proxies()["http"] == "http://user%2Fname:pa%3Ass%2Fword@proxy.example.com:8080"
