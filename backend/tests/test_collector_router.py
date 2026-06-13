from __future__ import annotations

from collections.abc import Generator
from datetime import date
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app import models as _models  # noqa: F401
from app.database import Base, get_db
from app.main import create_app
from app.models.site_daily_report import SiteDailyReport


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


class DummyHttpxResponse:
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


def test_operator_can_import_callback_json(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    create_account = client.post(
        "/api/v1/operator/accounts",
        json={"name": "oauth-json-account", "external_account_id": "ext-oauth-json", "status": "active"},
    )
    account_id = create_account.json()["id"]

    create_oauth_app = client.post(
        "/api/v1/operator/oauth-apps",
        json={
            "account_id": account_id,
            "client_id": "google-client-id-json",
            "client_secret": "google-client-secret-json",
            "redirect_uri": "https://jwtnx.com/oauth/google/callback",
            "scopes": "https://www.googleapis.com/auth/dfp",
        },
    )
    oauth_app_id = create_oauth_app.json()["id"]

    authorization_url = client.post(f"/api/v1/operator/oauth-apps/{oauth_app_id}/authorization-url")
    authorization_payload = authorization_url.json()

    def fake_post(url: str, data: dict[str, str], timeout: int) -> DummyResponse:
        assert url == "https://oauth2.googleapis.com/token"
        assert data["code"] == "callback-json-code"
        assert data["redirect_uri"] == "https://jwtnx.com/oauth/google/callback"
        assert timeout == 30
        return DummyResponse(
            200,
            {
                "access_token": "access-token-json-router",
                "refresh_token": "refresh-token-json-router",
                "expires_in": 1800,
                "scope": "https://www.googleapis.com/auth/dfp",
                "token_type": "Bearer",
            },
        )

    from app.collectors import oauth_service

    monkeypatch.setattr(oauth_service.requests, "post", fake_post)

    response = client.post(
        "/api/v1/operator/oauth-apps/import-callback-json",
        json={
            "state": authorization_payload["state"],
            "code": "callback-json-code",
            "redirect_uri": "https://jwtnx.com/oauth/google/callback",
            "callback_url": (
                "https://jwtnx.com/oauth/google/callback"
                f"?state={authorization_payload['state']}&code=callback-json-code"
            ),
            "scope": "https://www.googleapis.com/auth/dfp",
            "iss": "https://accounts.google.com",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "oauth_app_id": oauth_app_id,
        "account_id": account_id,
        "authorization_status": "authorized",
        "refresh_token_present": True,
    }


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


def test_operator_instance_can_store_mid_platform_node_config(client: TestClient) -> None:
    create_account = client.post(
        "/api/v1/operator/accounts",
        json={"name": "account-node-config", "external_account_id": "ext-node-config", "status": "active"},
    )
    account_id = create_account.json()["id"]

    create_instance = client.post(
        "/api/v1/operator/instances",
        json={
            "account_id": account_id,
            "name": "collector-node-config",
            "instance_token": "node-config-token",
            "status": "ready",
            "expected_egress_ip": "203.0.113.20",
            "report_base_url": "https://node-a.example.com",
            "report_account_key": "node-a-account",
            "report_token": "node-a-report-token",
        },
    )

    assert create_instance.status_code == 201
    assert create_instance.json()["report_base_url"] == "https://node-a.example.com"
    assert create_instance.json()["report_account_key"] == "node-a-account"
    assert create_instance.json()["report_token_present"] is True

    list_instances = client.get("/api/v1/operator/instances")
    assert list_instances.status_code == 200
    assert list_instances.json()["items"][0]["report_base_url"] == "https://node-a.example.com"
    assert list_instances.json()["items"][0]["report_account_key"] == "node-a-account"
    assert list_instances.json()["items"][0]["report_token_present"] is True
    assert "report_token" not in list_instances.json()["items"][0]


def test_operator_can_generate_remote_site_daily_report(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.collectors import service

    account_one = client.post(
        "/api/v1/operator/accounts",
        json={"name": "account-remote-a", "external_account_id": "ext-remote-a", "status": "active"},
    ).json()
    account_two = client.post(
        "/api/v1/operator/accounts",
        json={"name": "account-remote-b", "external_account_id": "ext-remote-b", "status": "active"},
    ).json()

    instance_one = client.post(
        "/api/v1/operator/instances",
        json={
            "account_id": account_one["id"],
            "name": "collector-remote-a",
            "instance_token": "token-remote-a",
            "status": "ready",
            "report_base_url": "https://node-a.example.com",
            "report_account_key": "a1",
            "report_token": "token-a",
        },
    ).json()
    instance_two = client.post(
        "/api/v1/operator/instances",
        json={
            "account_id": account_two["id"],
            "name": "collector-remote-b",
            "instance_token": "token-remote-b",
            "status": "ready",
            "report_base_url": "https://node-b.example.com",
            "report_account_key": "b1",
            "report_token": "token-b",
        },
    ).json()

    def fake_get(url: str, params: dict[str, str], timeout: int) -> DummyHttpxResponse:
        assert timeout == 15
        if url == "https://node-a.example.com/ke/report.php":
            assert params["account_key"] == "a1"
            assert params["token"] == "token-a"
            return DummyHttpxResponse(
                200,
                {
                    "ok": True,
                    "account_key": "a1",
                    "report_date": "2026-05-14",
                    "has_run": True,
                    "run_status": "success",
                    "run_id": 41,
                    "row_count": 2,
                    "error_message": None,
                    "items": [
                        {
                            "site_name": "alpha.example.com",
                            "responses_served": 100,
                            "impressions": 80,
                            "clicks": 3,
                            "revenue": "2.500000",
                            "ecpm": "31.250000",
                        },
                        {
                            "site_name": "beta.example.com",
                            "responses_served": 50,
                            "impressions": 40,
                            "clicks": 1,
                            "revenue": "1.000000",
                            "ecpm": "25.000000",
                        },
                    ],
                    "request_id": "req-node-a",
                },
            )
        if url == "https://node-b.example.com/ke/report.php":
            assert params["account_key"] == "b1"
            assert params["token"] == "token-b"
            return DummyHttpxResponse(
                200,
                {
                    "ok": True,
                    "account_key": "b1",
                    "report_date": "2026-05-14",
                    "has_run": False,
                    "run_status": None,
                    "run_id": None,
                    "row_count": 0,
                    "error_message": None,
                    "items": [],
                    "request_id": "req-node-b",
                },
            )
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(service.httpx, "get", fake_get)

    response = client.get("/api/v1/operator/mid-platform/reports/site-daily", params={"report_date": "2026-05-14"})
    assert response.status_code == 200
    body = response.json()

    assert body["summary"] == {
        "report_date": "2026-05-14",
        "requested_node_count": 2,
        "success_node_count": 1,
        "no_snapshot_node_count": 1,
        "error_node_count": 0,
        "row_count": 2,
        "total_responses_served": 150,
        "total_impressions": 120,
        "total_clicks": 4,
        "total_revenue": 3.5,
    }
    assert body["items"] == [
        {
            "account_id": account_one["id"],
            "account_name": "account-remote-a",
            "instance_id": instance_one["id"],
            "instance_name": "collector-remote-a",
            "node_base_url": "https://node-a.example.com",
            "node_account_key": "a1",
            "report_date": "2026-05-14",
            "site_name": "alpha.example.com",
            "responses_served": 100,
            "impressions": 80,
            "clicks": 3,
            "revenue": 2.5,
            "ecpm": 31.25,
            "source_run_id": 41,
        },
        {
            "account_id": account_one["id"],
            "account_name": "account-remote-a",
            "instance_id": instance_one["id"],
            "instance_name": "collector-remote-a",
            "node_base_url": "https://node-a.example.com",
            "node_account_key": "a1",
            "report_date": "2026-05-14",
            "site_name": "beta.example.com",
            "responses_served": 50,
            "impressions": 40,
            "clicks": 1,
            "revenue": 1.0,
            "ecpm": 25.0,
            "source_run_id": 41,
        },
    ]
    assert body["node_results"] == [
        {
            "account_id": account_one["id"],
            "account_name": "account-remote-a",
            "instance_id": instance_one["id"],
            "instance_name": "collector-remote-a",
            "node_base_url": "https://node-a.example.com",
            "node_account_key": "a1",
            "source_state": "success",
            "source_http_status": 200,
            "source_run_id": 41,
            "row_count": 2,
            "message": None,
        },
        {
            "account_id": account_two["id"],
            "account_name": "account-remote-b",
            "instance_id": instance_two["id"],
            "instance_name": "collector-remote-b",
            "node_base_url": "https://node-b.example.com",
            "node_account_key": "b1",
            "source_state": "no_snapshot",
            "source_http_status": 200,
            "source_run_id": None,
            "row_count": 0,
            "message": None,
        },
    ]


def test_operator_can_generate_remote_account_daily_report(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.collectors import service

    account_one = client.post(
        "/api/v1/operator/accounts",
        json={"name": "account-summary-a", "external_account_id": "ext-summary-a", "status": "active"},
    ).json()
    account_two = client.post(
        "/api/v1/operator/accounts",
        json={"name": "account-summary-b", "external_account_id": "ext-summary-b", "status": "active"},
    ).json()

    client.post(
        "/api/v1/operator/instances",
        json={
            "account_id": account_one["id"],
            "name": "collector-summary-a",
            "instance_token": "token-summary-a",
            "status": "ready",
            "report_base_url": "https://summary-a.example.com",
            "report_account_key": "sum-a",
            "report_token": "token-sum-a",
        },
    )
    client.post(
        "/api/v1/operator/instances",
        json={
            "account_id": account_two["id"],
            "name": "collector-summary-b",
            "instance_token": "token-summary-b",
            "status": "ready",
            "report_base_url": "https://summary-b.example.com",
            "report_account_key": "sum-b",
            "report_token": "token-sum-b",
        },
    )

    payload_map = {
        "https://summary-a.example.com/ke/report.php": {
            "ok": True,
            "account_key": "sum-a",
            "report_date": "2026-05-15",
            "has_run": True,
            "run_status": "success",
            "run_id": 52,
            "row_count": 2,
            "error_message": None,
            "items": [
                {
                    "site_name": "summary-a-1.example.com",
                    "responses_served": 20,
                    "impressions": 18,
                    "clicks": 1,
                    "revenue": "0.500000",
                    "ecpm": "27.777778",
                },
                {
                    "site_name": "summary-a-2.example.com",
                    "responses_served": 30,
                    "impressions": 21,
                    "clicks": 2,
                    "revenue": "1.000000",
                    "ecpm": "47.619048",
                },
            ],
            "request_id": "req-summary-a",
        },
        "https://summary-b.example.com/ke/report.php": {
            "ok": True,
            "account_key": "sum-b",
            "report_date": "2026-05-15",
            "has_run": True,
            "run_status": "success",
            "run_id": 53,
            "row_count": 1,
            "error_message": None,
            "items": [
                {
                    "site_name": "summary-b-1.example.com",
                    "responses_served": 10,
                    "impressions": 10,
                    "clicks": 0,
                    "revenue": "0.250000",
                    "ecpm": "25.000000",
                }
            ],
            "request_id": "req-summary-b",
        },
    }

    def fake_get(url: str, params: dict[str, str], timeout: int) -> DummyHttpxResponse:
        assert timeout == 15
        return DummyHttpxResponse(200, payload_map[url])

    monkeypatch.setattr(service.httpx, "get", fake_get)

    response = client.get("/api/v1/operator/mid-platform/reports/account-daily", params={"report_date": "2026-05-15"})
    assert response.status_code == 200
    body = response.json()

    assert body["summary"] == {
        "report_date": "2026-05-15",
        "requested_node_count": 2,
        "success_node_count": 2,
        "no_snapshot_node_count": 0,
        "error_node_count": 0,
        "row_count": 2,
        "total_responses_served": 60,
        "total_impressions": 49,
        "total_clicks": 3,
        "total_revenue": 1.75,
    }
    assert body["items"] == [
        {
            "account_id": account_one["id"],
            "account_name": "account-summary-a",
            "instance_id": 1,
            "instance_name": "collector-summary-a",
            "node_base_url": "https://summary-a.example.com",
            "node_account_key": "sum-a",
            "report_date": "2026-05-15",
            "site_count": 2,
            "responses_served": 50,
            "impressions": 39,
            "clicks": 3,
            "revenue": 1.5,
            "ecpm": 38.461538,
            "source_run_id": 52,
        },
        {
            "account_id": account_two["id"],
            "account_name": "account-summary-b",
            "instance_id": 2,
            "instance_name": "collector-summary-b",
            "node_base_url": "https://summary-b.example.com",
            "node_account_key": "sum-b",
            "report_date": "2026-05-15",
            "site_count": 1,
            "responses_served": 10,
            "impressions": 10,
            "clicks": 0,
            "revenue": 0.25,
            "ecpm": 25.0,
            "source_run_id": 53,
        },
    ]


def test_operator_can_list_mid_platform_link_resources(client: TestClient) -> None:
    create_account = client.post(
        "/api/v1/operator/accounts",
        json={"name": "account-links", "external_account_id": "ext-links", "status": "active"},
    )
    account_id = create_account.json()["id"]

    db: Session = client.app.dependency_overrides[get_db]().__next__()
    try:
        db.add(
            SiteDailyReport(
                account_id=account_id,
                report_date=date(2026, 5, 14),
                url_id="url-1",
                url="alpha.example.com",
                responses_served=10,
                impressions=8,
                clicks=1,
                revenue=Decimal("1.250000"),
                ecpm=Decimal("156.250000"),
            )
        )
        db.commit()
    finally:
        db.close()

    create_instance = client.post(
        "/api/v1/operator/instances",
        json={
            "account_id": account_id,
            "name": "collector-links",
            "instance_token": "token-links",
            "status": "ready",
            "report_base_url": "https://node-links.example.com",
            "report_account_key": "a-links",
            "report_token": "token-links",
        },
    )
    assert create_instance.status_code == 201

    response = client.get("/api/v1/operator/mid-platform/resources/links")
    assert response.status_code == 200
    assert response.json()["items"] == [
        {
            "account_id": account_id,
            "account_name": "account-links",
            "instance_id": 1,
            "instance_name": "collector-links",
            "node_base_url": "https://node-links.example.com",
            "node_account_key": "a-links",
            "site_name": "alpha.example.com",
            "link_key": "url-1",
            "link_name": "url-1",
            "destination_url": None,
            "status": "active",
        }
    ]


def test_operator_can_generate_mid_platform_link_daily_report(client: TestClient) -> None:
    create_account = client.post(
        "/api/v1/operator/accounts",
        json={"name": "account-link-daily", "external_account_id": "ext-link-daily", "status": "active"},
    )
    account_id = create_account.json()["id"]

    create_instance = client.post(
        "/api/v1/operator/instances",
        json={
            "account_id": account_id,
            "name": "collector-link-daily",
            "instance_token": "token-link-daily",
            "status": "ready",
            "report_base_url": "https://node-link-daily.example.com",
            "report_account_key": "a-link-daily",
            "report_token": "token-link-daily",
        },
    )
    assert create_instance.status_code == 201

    db: Session = client.app.dependency_overrides[get_db]().__next__()
    try:
        db.add(
            SiteDailyReport(
                account_id=account_id,
                report_date=date(2026, 5, 14),
                url_id="url-1",
                url="alpha.example.com",
                responses_served=100,
                impressions=80,
                clicks=3,
                revenue=Decimal("12.500000"),
                ecpm=Decimal("156.250000"),
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.get("/api/v1/operator/mid-platform/reports/link-daily", params={"report_date": "2026-05-14"})
    assert response.status_code == 200
    assert response.json()["summary"] == {
        "report_date": "2026-05-14",
        "requested_node_count": 1,
        "success_node_count": 1,
        "no_snapshot_node_count": 0,
        "error_node_count": 0,
        "row_count": 1,
        "total_responses_served": 100,
        "total_impressions": 80,
        "total_clicks": 3,
        "total_revenue": 12.5,
    }
    assert response.json()["items"] == [
        {
            "account_id": account_id,
            "account_name": "account-link-daily",
            "instance_id": 1,
            "instance_name": "collector-link-daily",
            "node_base_url": "https://node-link-daily.example.com",
            "node_account_key": "a-link-daily",
            "report_date": "2026-05-14",
            "site_name": "alpha.example.com",
            "link_key": "url-1",
            "responses_served": 100,
            "impressions": 80,
            "clicks": 3,
            "revenue": 12.5,
            "ecpm": 156.25,
            "source_run_id": None,
        }
    ]


def test_operator_can_list_mid_platform_account_resources(client: TestClient) -> None:
    create_account = client.post(
        "/api/v1/operator/accounts",
        json={"name": "account-resource-a", "external_account_id": "net-123", "status": "active"},
    )
    account_id = create_account.json()["id"]

    create_instance = client.post(
        "/api/v1/operator/instances",
        json={
            "account_id": account_id,
            "name": "collector-resource-a",
            "instance_token": "token-resource-a",
            "status": "ready",
            "report_base_url": "https://node-resource-a.example.com",
            "report_account_key": "a-resource",
            "report_token": "token-resource-a",
        },
    )
    assert create_instance.status_code == 201

    response = client.get("/api/v1/operator/mid-platform/resources/accounts")
    assert response.status_code == 200
    assert response.json()["items"] == [
        {
            "account_id": account_id,
            "account_name": "account-resource-a",
            "external_account_key": "a-resource",
            "network_code": "net-123",
            "status": "active",
        }
    ]


def test_operator_can_list_mid_platform_node_and_site_resources(client: TestClient) -> None:
    create_account = client.post(
        "/api/v1/operator/accounts",
        json={"name": "account-resource-b", "external_account_id": "net-456", "status": "active"},
    )
    account_id = create_account.json()["id"]

    create_instance = client.post(
        "/api/v1/operator/instances",
        json={
            "account_id": account_id,
            "name": "collector-resource-b",
            "instance_token": "token-resource-b",
            "status": "ready",
            "report_base_url": "https://node-resource-b.example.com",
            "report_account_key": "b-resource",
            "report_token": "token-resource-b",
        },
    )
    instance_id = create_instance.json()["id"]

    db: Session = client.app.dependency_overrides[get_db]().__next__()
    try:
        db.add(
            SiteDailyReport(
                account_id=account_id,
                report_date=date(2026, 5, 15),
                url_id="site-url-1",
                url="resource.example.com",
                responses_served=5,
                impressions=4,
                clicks=1,
                revenue=Decimal("0.500000"),
                ecpm=Decimal("125.000000"),
            )
        )
        db.commit()
    finally:
        db.close()

    node_response = client.get("/api/v1/operator/mid-platform/resources/nodes")
    assert node_response.status_code == 200
    assert node_response.json()["items"] == [
        {
            "account_id": account_id,
            "account_name": "account-resource-b",
            "instance_id": instance_id,
            "instance_name": "collector-resource-b",
            "node_base_url": "https://node-resource-b.example.com",
            "node_account_key": "b-resource",
            "status": "active",
        }
    ]

    site_response = client.get("/api/v1/operator/mid-platform/resources/sites")
    assert site_response.status_code == 200
    assert site_response.json()["items"] == [
        {
            "account_id": account_id,
            "account_name": "account-resource-b",
            "instance_id": instance_id,
            "instance_name": "collector-resource-b",
            "node_base_url": "https://node-resource-b.example.com",
            "node_account_key": "b-resource",
            "site_name": "resource.example.com",
            "status": "active",
        }
    ]
