from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app import models as _models  # noqa: F401
from app.database import Base, get_db
from app.main import create_app


@pytest.fixture()
def client(tmp_path: Path) -> Generator[TestClient, None, None]:
    database_path = tmp_path / "collector-router.db"
    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session)
    Base.metadata.create_all(engine)

    app = create_app()

    def override_get_db() -> Generator[Session, None, None]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    engine.dispose()


class DummyResponse:
    def __init__(self, status_code: int, payload: dict[str, object]) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict[str, object]:
        return self._payload


def test_operator_and_collector_workflow_happy_path(client: TestClient) -> None:
    create_account = client.post(
        "/api/v1/operator/accounts",
        json={"name": "account-one", "external_account_id": "ext-1", "status": "active"},
    )
    assert create_account.status_code == 201
    account_id = create_account.json()["id"]

    list_accounts = client.get("/api/v1/operator/accounts")
    assert list_accounts.status_code == 200
    assert [item["id"] for item in list_accounts.json()["items"]] == [account_id]

    create_instance = client.post(
        "/api/v1/operator/instances",
        json={
            "account_id": account_id,
            "name": "collector-a",
            "instance_token": "token-collector-a",
            "status": "ready",
            "expected_egress_ip": "203.0.113.10",
        },
    )
    assert create_instance.status_code == 201
    instance_id = create_instance.json()["id"]
    assert create_instance.json()["instance_token"] == "token-collector-a"

    list_instances = client.get("/api/v1/operator/instances")
    assert list_instances.status_code == 200
    assert [item["id"] for item in list_instances.json()["items"]] == [instance_id]
    assert "instance_token" not in list_instances.json()["items"][0]

    create_proxy = client.post(
        "/api/v1/operator/proxies",
        json={
            "account_id": account_id,
            "collector_instance_id": instance_id,
            "provider_name": "proxyco",
            "protocol": "http",
            "host": "proxy.example.com",
            "port": 8080,
            "username": "proxy-user",
            "password": "proxy-pass",
            "expected_egress_ip": "203.0.113.10",
            "status": "active",
        },
    )
    assert create_proxy.status_code == 201

    list_proxies = client.get("/api/v1/operator/proxies")
    assert list_proxies.status_code == 200
    assert [item["collector_instance_id"] for item in list_proxies.json()["items"]] == [instance_id]

    create_task = client.post(
        "/api/v1/operator/tasks",
        json={
            "account_id": account_id,
            "collector_instance_id": instance_id,
            "task_type": "report_fetch",
            "report_date": "2026-05-21",
            "status": "pending",
        },
    )
    assert create_task.status_code == 201
    task_id = create_task.json()["id"]

    list_tasks = client.get("/api/v1/operator/tasks")
    assert list_tasks.status_code == 200
    assert [item["id"] for item in list_tasks.json()["items"]] == [task_id]

    collector_headers = {"Authorization": "Bearer token-collector-a"}

    heartbeat = client.post(
        "/api/v1/collector/heartbeat",
        headers=collector_headers,
        json={"status": "ready", "observed_egress_ip": "203.0.113.10"},
    )
    assert heartbeat.status_code == 200
    assert heartbeat.json()["instance_id"] == instance_id
    assert heartbeat.json()["status"] == "ready"

    next_task = client.get("/api/v1/collector/tasks/next", headers=collector_headers)
    assert next_task.status_code == 200
    assert next_task.json()["id"] == task_id
    assert next_task.json()["status"] == "in_progress"

    batch_callback = client.post(
        f"/api/v1/collector/tasks/{task_id}/batches",
        headers=collector_headers,
        json={"batch_key": "page-1", "row_count": 25, "payload_hash": "hash-1"},
    )
    assert batch_callback.status_code == 201
    assert batch_callback.json()["duplicate"] is False

    status_callback = client.post(
        f"/api/v1/collector/tasks/{task_id}/status",
        headers=collector_headers,
        json={"status": "succeeded", "message": "batch uploaded"},
    )
    assert status_callback.status_code == 200
    assert status_callback.json()["status"] == "succeeded"

    list_tasks_after = client.get("/api/v1/operator/tasks")
    assert list_tasks_after.status_code == 200
    assert list_tasks_after.json()["items"][0]["status"] == "succeeded"


def test_operator_can_create_list_and_authorize_oauth_apps(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    create_account = client.post(
        "/api/v1/operator/accounts",
        json={"name": "oauth-account", "external_account_id": "ext-oauth", "status": "active"},
    )
    account_id = create_account.json()["id"]

    create_oauth_app = client.post(
        "/api/v1/operator/oauth-apps",
        json={
            "account_id": account_id,
            "client_id": "google-client-id",
            "client_secret": "google-client-secret",
            "redirect_uri": "https://control.example.com/api/v1/oauth/google/callback",
            "scopes": "https://www.googleapis.com/auth/dfp",
        },
    )
    assert create_oauth_app.status_code == 201
    oauth_app_id = create_oauth_app.json()["id"]
    assert create_oauth_app.json()["authorization_status"] == "pending"

    list_oauth_apps = client.get("/api/v1/operator/oauth-apps")
    assert list_oauth_apps.status_code == 200
    assert [item["id"] for item in list_oauth_apps.json()["items"]] == [oauth_app_id]
    assert list_oauth_apps.json()["items"][0]["account_id"] == account_id

    authorization_url = client.post(f"/api/v1/operator/oauth-apps/{oauth_app_id}/authorization-url")
    assert authorization_url.status_code == 200
    authorization_payload = authorization_url.json()
    parsed = urlparse(authorization_payload["authorization_url"])
    query = parse_qs(parsed.query)
    assert query["client_id"] == ["google-client-id"]
    assert query["state"] == [authorization_payload["state"]]

    def fake_post(url: str, data: dict[str, str], timeout: int) -> DummyResponse:
        assert url == "https://oauth2.googleapis.com/token"
        assert data["code"] == "authorization-code"
        assert data["client_id"] == "google-client-id"
        assert data["client_secret"] == "google-client-secret"
        assert data["redirect_uri"] == "https://control.example.com/api/v1/oauth/google/callback"
        assert data["grant_type"] == "authorization_code"
        assert timeout == 30
        return DummyResponse(
            200,
            {
                "access_token": "access-token-router",
                "refresh_token": "refresh-token-router",
                "expires_in": 1800,
                "scope": "https://www.googleapis.com/auth/dfp",
                "token_type": "Bearer",
            },
        )

    from app.collectors import oauth_service

    monkeypatch.setattr(oauth_service.requests, "post", fake_post)

    callback = client.get(
        "/api/v1/oauth/google/callback",
        params={"state": authorization_payload["state"], "code": "authorization-code"},
    )
    assert callback.status_code == 200
    assert callback.json() == {
        "oauth_app_id": oauth_app_id,
        "account_id": account_id,
        "authorization_status": "authorized",
        "refresh_token_present": True,
    }

    list_after_callback = client.get("/api/v1/operator/oauth-apps")
    assert list_after_callback.status_code == 200
    oauth_item = list_after_callback.json()["items"][0]
    assert oauth_item["authorization_status"] == "authorized"
    assert oauth_item["refresh_token_present"] is True
    assert oauth_item["access_token_expires_at"] is not None

    create_instance = client.post(
        "/api/v1/operator/instances",
        json={
            "account_id": account_id,
            "name": "collector-oauth",
            "instance_token": "oauth-instance-token",
            "status": "ready",
            "expected_egress_ip": "203.0.113.10",
        },
    )
    instance_id = create_instance.json()["id"]

    create_proxy = client.post(
        "/api/v1/operator/proxies",
        json={
            "account_id": account_id,
            "collector_instance_id": instance_id,
            "provider_name": "proxyco",
            "protocol": "http",
            "host": "proxy.example.com",
            "port": 8080,
            "username": "proxy-user",
            "password": "proxy-pass",
            "expected_egress_ip": "203.0.113.10",
            "status": "active",
        },
    )
    assert create_proxy.status_code == 201

    runtime_config = client.get(
        "/api/v1/collector/runtime-config",
        headers={"Authorization": "Bearer oauth-instance-token"},
    )
    assert runtime_config.status_code == 200
    assert runtime_config.headers["cache-control"] == "no-store"
    assert runtime_config.json()["google"] == {
        "fetch_mode": "admanager_soap",
        "admanager_network_code": "ext-oauth",
        "google_oauth_client_id": "google-client-id",
        "google_oauth_client_secret": "google-client-secret",
        "google_oauth_refresh_token": "refresh-token-router",
    }


def test_google_callback_rejects_unknown_oauth_state(client: TestClient) -> None:
    response = client.get(
        "/api/v1/oauth/google/callback",
        params={"state": "missing-state", "code": "authorization-code"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "OAuth authorization state is invalid or expired"


def test_collector_routes_reject_invalid_instance_token(client: TestClient) -> None:
    create_account = client.post(
        "/api/v1/operator/accounts",
        json={"name": "account-auth", "external_account_id": "ext-auth", "status": "active"},
    )
    account_id = create_account.json()["id"]

    create_instance = client.post(
        "/api/v1/operator/instances",
        json={
            "account_id": account_id,
            "name": "collector-auth",
            "instance_token": "valid-token",
            "status": "ready",
        },
    )
    assert create_instance.status_code == 201

    response = client.get(
        "/api/v1/collector/tasks/next",
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid collector token"


def test_collector_next_task_returns_204_when_queue_is_empty(client: TestClient) -> None:
    create_account = client.post(
        "/api/v1/operator/accounts",
        json={"name": "account-empty", "external_account_id": "ext-empty", "status": "active"},
    )
    account_id = create_account.json()["id"]

    create_instance = client.post(
        "/api/v1/operator/instances",
        json={
            "account_id": account_id,
            "name": "collector-empty",
            "instance_token": "empty-token",
            "status": "ready",
        },
    )
    assert create_instance.status_code == 201

    response = client.get("/api/v1/collector/tasks/next", headers={"Authorization": "Bearer empty-token"})
    assert response.status_code == 204


def test_operator_create_account_returns_409_for_duplicate_name(client: TestClient) -> None:
    first = client.post(
        "/api/v1/operator/accounts",
        json={"name": "duplicate-account", "external_account_id": "ext-dup", "status": "active"},
    )
    assert first.status_code == 201

    second = client.post(
        "/api/v1/operator/accounts",
        json={"name": "duplicate-account", "external_account_id": "ext-dup-2", "status": "active"},
    )
    assert second.status_code == 409


def test_task_status_rejects_invalid_terminal_regression(client: TestClient) -> None:
    create_account = client.post(
        "/api/v1/operator/accounts",
        json={"name": "account-status", "external_account_id": "ext-status", "status": "active"},
    )
    account_id = create_account.json()["id"]

    create_instance = client.post(
        "/api/v1/operator/instances",
        json={
            "account_id": account_id,
            "name": "collector-status",
            "instance_token": "token-status",
            "status": "ready",
        },
    )
    instance_id = create_instance.json()["id"]

    create_task = client.post(
        "/api/v1/operator/tasks",
        json={
            "account_id": account_id,
            "collector_instance_id": instance_id,
            "task_type": "report_fetch",
            "report_date": "2026-05-21",
            "status": "pending",
        },
    )
    task_id = create_task.json()["id"]
    headers = {"Authorization": "Bearer token-status"}

    assert client.get("/api/v1/collector/tasks/next", headers=headers).status_code == 200
    assert client.post(
        f"/api/v1/collector/tasks/{task_id}/status",
        headers=headers,
        json={"status": "succeeded", "message": "done"},
    ).status_code == 200
    completed = client.get("/api/v1/operator/tasks").json()["items"][0]
    assert completed["started_at"] is not None
    assert completed["finished_at"] is not None
    first_started_at = completed["started_at"]

    regression = client.post(
        f"/api/v1/collector/tasks/{task_id}/status",
        headers=headers,
        json={"status": "in_progress", "message": "retry"},
    )
    assert regression.status_code == 409
    after_regression = client.get("/api/v1/operator/tasks").json()["items"][0]
    assert after_regression["started_at"] == first_started_at
