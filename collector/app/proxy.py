from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote


class ProxyConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ProxyConfig:
    protocol: str
    host: str
    port: int
    username: str | None
    password: str | None
    expected_egress_ip: str

    def __post_init__(self) -> None:
        if self.protocol not in {"http", "https", "socks5"}:
            raise ProxyConfigError("protocol must be one of http, https, or socks5")
        if not self.host:
            raise ProxyConfigError("host is required")
        if not 1 <= self.port <= 65535:
            raise ProxyConfigError("port must be between 1 and 65535")
        if bool(self.username) != bool(self.password):
            raise ProxyConfigError("proxy auth requires both username and password")
        if not self.expected_egress_ip:
            raise ProxyConfigError("expected_egress_ip is required")

    def as_requests_proxies(self) -> dict[str, str]:
        credentials = ""
        if self.username and self.password:
            credentials = f"{quote(self.username, safe='')}:{quote(self.password, safe='')}@"
        proxy_url = f"{self.protocol}://{credentials}{self.host}:{self.port}"
        return {"http": proxy_url, "https": proxy_url}
