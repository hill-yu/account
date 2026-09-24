from __future__ import annotations

from dataclasses import dataclass

from app.proxy import ProxyConfig
from app.vps_models import AdxAccount, AdxAccountProxy


@dataclass(frozen=True)
class ProxyRoute:
    mode: str
    proxy_type: str | None = None
    proxy_host: str | None = None
    proxy_port: int | None = None
    proxy_username: str | None = None
    proxy_password: str | None = None
    expected_egress_ip: str | None = None


class ProxyResolver:
    def resolve(self, *, account: AdxAccount, proxy_binding: AdxAccountProxy | None) -> ProxyRoute:
        if proxy_binding is None:
            return ProxyRoute(mode="direct")
        if proxy_binding.proxy_type == "direct":
            return ProxyRoute(mode="direct", expected_egress_ip=proxy_binding.expected_egress_ip)

        config = ProxyConfig(
            protocol=proxy_binding.proxy_type,
            host=proxy_binding.proxy_host or "",
            port=proxy_binding.proxy_port or 0,
            username=proxy_binding.proxy_username,
            password=proxy_binding.proxy_password,
            expected_egress_ip=proxy_binding.expected_egress_ip or "",
        )
        return ProxyRoute(
            mode="configured_proxy",
            proxy_type=config.protocol,
            proxy_host=config.host,
            proxy_port=config.port,
            proxy_username=config.username,
            proxy_password=config.password,
            expected_egress_ip=config.expected_egress_ip,
        )
