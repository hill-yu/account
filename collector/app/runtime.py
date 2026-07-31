from __future__ import annotations

from app.control_plane_client import ControlPlaneClient
from app.egress import EgressChecker
from app.fetcher import Fetcher, build_fetcher
from app.models import RuntimeResult, RuntimeSettings
from app.proxy import ProxyConfig


class CollectorRuntime:
    def __init__(
        self,
        *,
        settings: RuntimeSettings,
        control_plane_client: ControlPlaneClient,
        egress_checker: EgressChecker,
        fetcher: Fetcher,
    ) -> None:
        self.settings = settings
        self.control_plane_client = control_plane_client
        self.egress_checker = egress_checker
        self.fetcher = fetcher
        self.proxy_config = ProxyConfig(
            protocol=settings.proxy_protocol,
            host=settings.proxy_host,
            port=settings.proxy_port,
            username=settings.proxy_username,
            password=settings.proxy_password,
            expected_egress_ip=settings.expected_egress_ip,
        )

    @classmethod
    def from_settings(
        cls,
        settings: RuntimeSettings,
        *,
        fetcher: Fetcher | None = None,
    ) -> "CollectorRuntime":
        proxy_config = ProxyConfig(
            protocol=settings.proxy_protocol,
            host=settings.proxy_host,
            port=settings.proxy_port,
            username=settings.proxy_username,
            password=settings.proxy_password,
            expected_egress_ip=settings.expected_egress_ip,
        )
        control_plane_client = ControlPlaneClient(
            base_url=settings.control_plane_base_url,
            instance_token=settings.instance_token,
            timeout_seconds=settings.request_timeout_seconds,
        )
        egress_checker = EgressChecker(
            check_url=settings.egress_check_url,
            proxies=proxy_config.as_requests_proxies(),
            timeout_seconds=settings.request_timeout_seconds,
        )
        return cls(
            settings=settings,
            control_plane_client=control_plane_client,
            egress_checker=egress_checker,
            fetcher=fetcher or build_fetcher(settings),
        )

    def run_once(self) -> RuntimeResult:
        observed_egress_ip = self.egress_checker.get_observed_ip()
        if observed_egress_ip != self.settings.expected_egress_ip:
            self.control_plane_client.heartbeat(status="blocked", observed_egress_ip=observed_egress_ip)
            return RuntimeResult(outcome="blocked", reason="egress_ip_mismatch")

        self.control_plane_client.heartbeat(status="ready", observed_egress_ip=observed_egress_ip)

        task = self.control_plane_client.get_next_task()
        if task is None:
            return RuntimeResult(outcome="idle")

        try:
            batches = list(self.fetcher.fetch(task))
            for batch in batches:
                self.control_plane_client.submit_batch(task.id, batch)
            self.control_plane_client.update_task_status(
                task.id,
                "succeeded",
                f"uploaded {len(batches)} batches",
            )
            return RuntimeResult(outcome="succeeded", task_id=task.id)
        except Exception as exc:
            self.control_plane_client.update_task_status(task.id, "failed", str(exc))
            raise
