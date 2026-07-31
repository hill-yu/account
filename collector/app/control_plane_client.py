from __future__ import annotations

from typing import Any

import requests

from app.models import CollectorRuntimeConfig, CollectorTask, FetchBatch
from app.oauth_validation import OAuthValidationResult


class ControlPlaneClient:
    def __init__(
        self,
        *,
        base_url: str,
        instance_token: str,
        timeout_seconds: int,
        session: requests.Session | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._session = session or requests.Session()
        self._headers = {"Authorization": f"Bearer {instance_token}"}

    def heartbeat(self, *, status: str, observed_egress_ip: str) -> dict[str, Any]:
        response = self._session.post(
            f"{self._base_url}/api/v1/collector/heartbeat",
            headers=self._headers,
            json={"status": status, "observed_egress_ip": observed_egress_ip},
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        return response.json()

    def get_runtime_config(self) -> CollectorRuntimeConfig:
        response = self._session.get(
            f"{self._base_url}/api/v1/collector/runtime-config",
            headers=self._headers,
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        return CollectorRuntimeConfig.from_dict(response.json())

    def get_next_task(self) -> CollectorTask | None:
        response = self._session.get(
            f"{self._base_url}/api/v1/collector/tasks/next",
            headers=self._headers,
            timeout=self._timeout_seconds,
        )
        if response.status_code == 204:
            return None
        response.raise_for_status()
        return CollectorTask.from_dict(response.json())

    def submit_batch(self, task_id: int, batch: FetchBatch) -> dict[str, Any]:
        response = self._session.post(
            f"{self._base_url}/api/v1/collector/tasks/{task_id}/batches",
            headers=self._headers,
            json=batch.as_dict(),
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        return response.json()

    def update_task_status(
        self,
        task_id: int,
        status: str,
        message: str | None = None,
        failure_class: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": status, "message": message, "failure_class": failure_class}
        response = self._session.post(
            f"{self._base_url}/api/v1/collector/tasks/{task_id}/status",
            headers=self._headers,
            json=payload,
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        return response.json()

    def acknowledge_oauth_credential(self, *, task_id: int, result: OAuthValidationResult) -> dict[str, Any]:
        response = self._session.post(
            f"{self._base_url}/api/v1/collector/oauth/credential-ack",
            headers=self._headers,
            json={
                "task_id": task_id,
                "account_id": result.account_id,
                "credential_version": result.credential_version,
                "token_fingerprint": result.token_fingerprint,
                "network_code": result.network_code,
                "network_timezone": result.network_timezone,
                "granted_scopes": result.granted_scopes,
            },
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        return response.json()
