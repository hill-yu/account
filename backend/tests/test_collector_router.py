from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, date, datetime, timezone
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
from app.models.account_hourly_report import AccountHourlyReport
from app.models.site_daily_report import SiteDailyReport
from app.models.site_hourly_report import SiteHourlyReport


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


def test_operator_rejects_callback_json_with_callback_error(client: TestClient) -> None:
    create_account = client.post(
        "/api/v1/operator/accounts",
        json={"name": "oauth-json-error-account", "external_account_id": "ext-oauth-json-error", "status": "active"},
    )
    account_id = create_account.json()["id"]

    create_oauth_app = client.post(
        "/api/v1/operator/oauth-apps",
        json={
            "account_id": account_id,
            "client_id": "google-client-id-json-error",
            "client_secret": "google-client-secret-json-error",
            "redirect_uri": "https://jwtnx.com/oauth/google/callback",
            "scopes": "https://www.googleapis.com/auth/dfp",
        },
    )
    oauth_app_id = create_oauth_app.json()["id"]

    authorization_url = client.post(f"/api/v1/operator/oauth-apps/{oauth_app_id}/authorization-url")
    authorization_payload = authorization_url.json()

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
            "error": "access_denied",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "callback returned error"


def test_operator_rejects_callback_json_with_wrong_issuer(client: TestClient) -> None:
    create_account = client.post(
        "/api/v1/operator/accounts",
        json={"name": "oauth-json-issuer-account", "external_account_id": "ext-oauth-json-issuer", "status": "active"},
    )
    account_id = create_account.json()["id"]

    create_oauth_app = client.post(
        "/api/v1/operator/oauth-apps",
        json={
            "account_id": account_id,
            "client_id": "google-client-id-json-issuer",
            "client_secret": "google-client-secret-json-issuer",
            "redirect_uri": "https://jwtnx.com/oauth/google/callback",
            "scopes": "https://www.googleapis.com/auth/dfp",
        },
    )
    oauth_app_id = create_oauth_app.json()["id"]

    authorization_url = client.post(f"/api/v1/operator/oauth-apps/{oauth_app_id}/authorization-url")
    authorization_payload = authorization_url.json()

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
            "iss": "https://example.com",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "issuer mismatch"


def test_operator_rejects_callback_json_when_callback_query_state_or_code_mismatch(client: TestClient) -> None:
    create_account = client.post(
        "/api/v1/operator/accounts",
        json={"name": "oauth-json-mismatch-account", "external_account_id": "ext-oauth-json-mismatch", "status": "active"},
    )
    account_id = create_account.json()["id"]

    create_oauth_app = client.post(
        "/api/v1/operator/oauth-apps",
        json={
            "account_id": account_id,
            "client_id": "google-client-id-json-mismatch",
            "client_secret": "google-client-secret-json-mismatch",
            "redirect_uri": "https://jwtnx.com/oauth/google/callback",
            "scopes": "https://www.googleapis.com/auth/dfp",
        },
    )
    oauth_app_id = create_oauth_app.json()["id"]

    authorization_url = client.post(f"/api/v1/operator/oauth-apps/{oauth_app_id}/authorization-url")
    authorization_payload = authorization_url.json()

    wrong_state_response = client.post(
        "/api/v1/operator/oauth-apps/import-callback-json",
        json={
            "state": authorization_payload["state"],
            "code": "callback-json-code",
            "redirect_uri": "https://jwtnx.com/oauth/google/callback",
            "callback_url": "https://jwtnx.com/oauth/google/callback?state=wrong-state&code=callback-json-code",
        },
    )
    assert wrong_state_response.status_code == 422
    assert wrong_state_response.json()["detail"] == "callback state mismatch"

    wrong_code_response = client.post(
        "/api/v1/operator/oauth-apps/import-callback-json",
        json={
            "state": authorization_payload["state"],
            "code": "callback-json-code",
            "redirect_uri": "https://jwtnx.com/oauth/google/callback",
            "callback_url": (
                "https://jwtnx.com/oauth/google/callback"
                f"?state={authorization_payload['state']}&code=wrong-code"
            ),
        },
    )
    assert wrong_code_response.status_code == 422
    assert wrong_code_response.json()["detail"] == "callback code mismatch"


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
    assert body["timezone"] == "America/Los_Angeles"

    assert body["summary"] == {
        "report_date": "2026-05-14",
        "requested_node_count": 2,
        "success_node_count": 1,
        "no_snapshot_node_count": 1,
        "error_node_count": 0,
        "row_count": 2,
        "total_responses_served": 150,
        "total_requests": 0,
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
            "requests": 0,
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
            "requests": 0,
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
    assert body["timezone"] == "America/Los_Angeles"

    assert body["summary"] == {
        "report_date": "2026-05-15",
        "requested_node_count": 2,
        "success_node_count": 2,
        "no_snapshot_node_count": 0,
        "error_node_count": 0,
        "row_count": 2,
        "total_responses_served": 60,
        "total_requests": 0,
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
            "requests": 0,
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
            "requests": 0,
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
            "currency": "USD",
            "default_display_timezone": "America/Los_Angeles",
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
    assert response.json()["timezone"] == "America/Los_Angeles"
    assert response.json()["summary"] == {
        "report_date": "2026-05-14",
        "requested_node_count": 1,
        "success_node_count": 1,
        "no_snapshot_node_count": 0,
        "error_node_count": 0,
        "row_count": 1,
        "total_responses_served": 100,
        "total_requests": 0,
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
            "requests": 0,
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
            "timezone": "America/Los_Angeles",
            "default_display_timezone": "America/Los_Angeles",
            "currency": "USD",
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
            "currency": "USD",
            "default_display_timezone": "America/Los_Angeles",
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
            "currency": "USD",
            "default_display_timezone": "America/Los_Angeles",
            "status": "active",
        }
    ]


def test_operator_can_patch_account_timezone(client: TestClient) -> None:
    create_account = client.post(
        "/api/v1/operator/accounts",
        json={"name": "account-timezone", "external_account_id": "net-tz", "status": "active"},
    )
    account_id = create_account.json()["id"]

    response = client.patch(
        f"/api/v1/operator/accounts/{account_id}/timezone",
        json={"timezone": "Asia/Hong_Kong"},
    )

    assert response.status_code == 200
    assert response.json()["timezone"] == "Asia/Hong_Kong"


def test_operator_can_create_list_and_patch_fetch_schedule(client: TestClient) -> None:
    create_account = client.post(
        "/api/v1/operator/accounts",
        json={"name": "account-fetch-schedule", "external_account_id": "net-fetch", "status": "active"},
    )
    account_id = create_account.json()["id"]

    create_instance = client.post(
        "/api/v1/operator/instances",
        json={
            "account_id": account_id,
            "name": "collector-fetch-schedule",
            "instance_token": "token-fetch-schedule",
            "status": "ready",
            "report_base_url": "https://node-fetch.example.com",
            "report_account_key": "jwtnx",
            "report_token": "token-jwtnx",
        },
    )
    instance_id = create_instance.json()["id"]

    create_schedule = client.post(
        "/api/v1/operator/fetch-schedules",
        json={
            "account_id": account_id,
            "collector_instance_id": instance_id,
            "enabled": True,
            "mode": "daily_times",
            "daily_times": ["09:00", "21:00"],
            "interval_hours": None,
            "timezone": "Asia/Shanghai",
        },
    )
    assert create_schedule.status_code == 201
    created = create_schedule.json()
    schedule_id = created["id"]
    assert created["account_id"] == account_id
    assert created["collector_instance_id"] == instance_id
    assert created["enabled"] is True
    assert created["mode"] == "daily_times"
    assert created["daily_times"] == ["09:00", "21:00"]
    assert created["interval_hours"] is None
    assert created["timezone"] == "Asia/Shanghai"
    assert created["next_run_at"] is not None

    list_schedules = client.get("/api/v1/operator/fetch-schedules")
    assert list_schedules.status_code == 200
    assert list_schedules.json()["items"] == [created]

    patch_schedule = client.patch(
        f"/api/v1/operator/fetch-schedules/{schedule_id}",
        json={
            "enabled": False,
            "mode": "interval_hours",
            "daily_times": None,
            "interval_hours": 12,
            "timezone": "America/Los_Angeles",
        },
    )
    assert patch_schedule.status_code == 200
    assert patch_schedule.json()["id"] == schedule_id
    assert patch_schedule.json()["enabled"] is False
    assert patch_schedule.json()["mode"] == "interval_hours"
    assert patch_schedule.json()["daily_times"] is None
    assert patch_schedule.json()["interval_hours"] == 12
    assert patch_schedule.json()["timezone"] == "America/Los_Angeles"
    assert patch_schedule.json()["next_run_at"] is None


def test_operator_enabling_fetch_schedule_recomputes_next_run_at(client: TestClient) -> None:
    create_account = client.post(
        "/api/v1/operator/accounts",
        json={"name": "account-fetch-enable", "external_account_id": "net-fetch-enable", "status": "active"},
    )
    account_id = create_account.json()["id"]

    create_instance = client.post(
        "/api/v1/operator/instances",
        json={
            "account_id": account_id,
            "name": "collector-fetch-enable",
            "instance_token": "token-fetch-enable",
            "status": "ready",
            "report_base_url": "https://node-fetch-enable.example.com",
            "report_account_key": "enable-a1",
            "report_token": "enable-token",
        },
    )
    instance_id = create_instance.json()["id"]

    create_schedule = client.post(
        "/api/v1/operator/fetch-schedules",
        json={
            "account_id": account_id,
            "collector_instance_id": instance_id,
            "enabled": False,
            "mode": "interval_hours",
            "daily_times": None,
            "interval_hours": 4,
            "timezone": "UTC",
        },
    )
    assert create_schedule.status_code == 201
    schedule_id = create_schedule.json()["id"]
    assert create_schedule.json()["next_run_at"] is None

    patch_schedule = client.patch(
        f"/api/v1/operator/fetch-schedules/{schedule_id}",
        json={"enabled": True},
    )
    assert patch_schedule.status_code == 200
    assert patch_schedule.json()["enabled"] is True
    assert patch_schedule.json()["next_run_at"] is not None
    next_run_at = datetime.fromisoformat(patch_schedule.json()["next_run_at"].replace("Z", "+00:00"))
    if next_run_at.tzinfo is None:
        next_run_at = next_run_at.replace(tzinfo=UTC)
    assert next_run_at.astimezone(UTC) >= datetime.now(UTC)


def test_manual_fetch_calls_real_fetch_php(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.collectors import service

    create_account = client.post(
        "/api/v1/operator/accounts",
        json={"name": "account-manual-fetch", "external_account_id": "net-manual", "status": "active"},
    )
    account_id = create_account.json()["id"]

    create_instance = client.post(
        "/api/v1/operator/instances",
        json={
            "account_id": account_id,
            "name": "collector-manual-fetch",
            "instance_token": "token-manual-fetch",
            "status": "ready",
            "report_base_url": "https://node.example.com",
            "report_account_key": "jwtnx",
            "report_token": "token-jwtnx",
        },
    )
    instance_id = create_instance.json()["id"]

    def fake_get(url: str, params: dict[str, str], timeout: int) -> DummyHttpxResponse:
        assert url == "https://node.example.com/ke/fetch.php"
        assert params == {
            "account_key": "jwtnx",
            "report_date": "2026-06-23",
            "token": "token-jwtnx",
        }
        assert timeout == 15
        return DummyHttpxResponse(
            200,
            {
                "ok": True,
                "status": "accepted",
                "run_id": 88,
                "request_id": "req-jwtnx",
                "message": "queued",
            },
        )

    monkeypatch.setattr(service.httpx, "get", fake_get)
    launched_instances: list[tuple[int, str]] = []

    def fake_launch_hourly_sync_runtime(instance) -> None:
        launched_instances.append((instance.id, instance.instance_token))

    monkeypatch.setattr(service, "_launch_hourly_sync_runtime", fake_launch_hourly_sync_runtime)

    response = client.post(
        "/api/v1/operator/fetch-schedules/manual-fetch",
        json={
            "account_id": account_id,
            "collector_instance_id": instance_id,
            "report_date": "2026-06-23",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "status": "accepted",
        "run_id": 88,
        "request_id": "req-jwtnx",
        "message": "queued",
        "hourly_sync_task_id": 1,
        "hourly_sync_task_status": "pending",
        "hourly_sync_task_created": True,
    }

    tasks_response = client.get("/api/v1/operator/tasks")
    assert tasks_response.status_code == 200
    assert tasks_response.json()["items"] == [
        {
            "id": 1,
            "account_id": account_id,
            "collector_instance_id": instance_id,
            "task_type": "report_fetch_hourly",
            "report_date": "2026-06-23",
            "status": "pending",
            "external_request_id": "req-jwtnx",
            "started_at": None,
            "finished_at": None,
            "created_at": tasks_response.json()["items"][0]["created_at"],
            "updated_at": tasks_response.json()["items"][0]["updated_at"],
        }
    ]
    assert launched_instances == [(instance_id, "token-manual-fetch")]


def test_manual_fetch_returns_existing_hourly_sync_task_when_already_active(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.collectors import service

    create_account = client.post(
        "/api/v1/operator/accounts",
        json={"name": "account-manual-conflict", "external_account_id": "net-manual-conflict", "status": "active"},
    )
    account_id = create_account.json()["id"]

    create_instance = client.post(
        "/api/v1/operator/instances",
        json={
            "account_id": account_id,
            "name": "collector-manual-conflict",
            "instance_token": "token-manual-conflict",
            "status": "ready",
            "report_base_url": "https://node-conflict.example.com",
            "report_account_key": "jwtnx",
            "report_token": "token-jwtnx",
        },
    )
    instance_id = create_instance.json()["id"]

    create_task = client.post(
        "/api/v1/operator/tasks",
        json={
            "account_id": account_id,
            "collector_instance_id": instance_id,
            "task_type": "report_fetch_hourly",
            "report_date": "2026-06-23",
            "status": "pending",
            "external_request_id": "existing-hourly-task",
        },
    )
    assert create_task.status_code == 201

    def fail_get(url: str, params: dict[str, str], timeout: int) -> DummyHttpxResponse:
        raise AssertionError("remote fetch should not be called when hourly sync task is already active")

    monkeypatch.setattr(service.httpx, "get", fail_get)
    monkeypatch.setattr(service, "_launch_hourly_sync_runtime", lambda instance: None)

    response = client.post(
        "/api/v1/operator/fetch-schedules/manual-fetch",
        json={
            "account_id": account_id,
            "collector_instance_id": instance_id,
            "report_date": "2026-06-23",
        },
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["hourly_sync_task_id"] == create_task.json()["id"]
    assert response.json()["hourly_sync_task_status"] == "pending"
    assert response.json()["hourly_sync_task_created"] is False


def test_manual_fetch_reuses_existing_hourly_sync_task(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.collectors import service

    create_account = client.post(
        "/api/v1/operator/accounts",
        json={"name": "account-manual-reuse", "external_account_id": "net-manual-reuse", "status": "active"},
    )
    account_id = create_account.json()["id"]

    create_instance = client.post(
        "/api/v1/operator/instances",
        json={
            "account_id": account_id,
            "name": "collector-manual-reuse",
            "instance_token": "token-manual-reuse",
            "status": "ready",
            "report_base_url": "https://node-reuse.example.com",
            "report_account_key": "lfmtmt",
            "report_token": "token-lfmtmt",
        },
    )
    instance_id = create_instance.json()["id"]

    create_task = client.post(
        "/api/v1/operator/tasks",
        json={
            "account_id": account_id,
            "collector_instance_id": instance_id,
            "task_type": "report_fetch_hourly",
            "report_date": "2026-07-06",
            "status": "pending",
            "external_request_id": "existing-hourly-task",
        },
    )
    assert create_task.status_code == 201

    monkeypatch.setattr(service.httpx, "get", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("remote fetch should not run")))
    launched_instances: list[int] = []
    monkeypatch.setattr(service, "_launch_hourly_sync_runtime", lambda instance: launched_instances.append(instance.id))

    response = client.post(
        "/api/v1/operator/fetch-schedules/manual-fetch",
        json={
            "account_id": account_id,
            "collector_instance_id": instance_id,
            "report_date": "2026-07-06",
        },
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["hourly_sync_task_id"] == create_task.json()["id"]
    assert response.json()["hourly_sync_task_status"] == "pending"
    assert response.json()["hourly_sync_task_created"] is False
    assert launched_instances == [instance_id]


def test_manual_fetch_rejects_instance_without_report_config(client: TestClient) -> None:
    create_account = client.post(
        "/api/v1/operator/accounts",
        json={"name": "account-manual-missing", "external_account_id": "net-manual-missing", "status": "active"},
    )
    account_id = create_account.json()["id"]

    create_instance = client.post(
        "/api/v1/operator/instances",
        json={
            "account_id": account_id,
            "name": "collector-manual-missing",
            "instance_token": "token-manual-missing",
            "status": "ready",
        },
    )
    instance_id = create_instance.json()["id"]

    response = client.post(
        "/api/v1/operator/fetch-schedules/manual-fetch",
        json={
            "account_id": account_id,
            "collector_instance_id": instance_id,
            "report_date": "2026-06-23",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Collector instance is missing report configuration"


def test_operator_fetch_schedule_patch_updates_current_mode_fields_without_requiring_mode(client: TestClient) -> None:
    create_account = client.post(
        "/api/v1/operator/accounts",
        json={"name": "account-fetch-patch", "external_account_id": "net-fetch-patch", "status": "active"},
    )
    account_id = create_account.json()["id"]

    create_instance = client.post(
        "/api/v1/operator/instances",
        json={
            "account_id": account_id,
            "name": "collector-fetch-patch",
            "instance_token": "token-fetch-patch",
            "status": "ready",
            "report_base_url": "https://node-fetch-patch.example.com",
            "report_account_key": "patch-account",
            "report_token": "patch-token",
        },
    )
    instance_id = create_instance.json()["id"]

    create_schedule = client.post(
        "/api/v1/operator/fetch-schedules",
        json={
            "account_id": account_id,
            "collector_instance_id": instance_id,
            "enabled": True,
            "mode": "daily_times",
            "daily_times": ["09:00", "21:00"],
            "interval_hours": None,
            "timezone": "Asia/Shanghai",
        },
    )
    schedule_id = create_schedule.json()["id"]

    patch_daily_times = client.patch(
        f"/api/v1/operator/fetch-schedules/{schedule_id}",
        json={"daily_times": ["10:00", "22:00"]},
    )
    assert patch_daily_times.status_code == 200
    assert patch_daily_times.json()["mode"] == "daily_times"
    assert patch_daily_times.json()["daily_times"] == ["10:00", "22:00"]
    assert patch_daily_times.json()["interval_hours"] is None

    patch_to_interval = client.patch(
        f"/api/v1/operator/fetch-schedules/{schedule_id}",
        json={
            "mode": "interval_hours",
            "daily_times": None,
            "interval_hours": 12,
        },
    )
    assert patch_to_interval.status_code == 200

    patch_interval_hours = client.patch(
        f"/api/v1/operator/fetch-schedules/{schedule_id}",
        json={"interval_hours": 6},
    )
    assert patch_interval_hours.status_code == 200
    assert patch_interval_hours.json()["mode"] == "interval_hours"
    assert patch_interval_hours.json()["daily_times"] is None
    assert patch_interval_hours.json()["interval_hours"] == 6


def test_collector_next_task_prefers_newest_hourly_sync_task(client: TestClient) -> None:
    create_account = client.post(
        "/api/v1/operator/accounts",
        json={"name": "account-task-priority", "external_account_id": "net-task-priority", "status": "active"},
    )
    account_id = create_account.json()["id"]

    create_instance = client.post(
        "/api/v1/operator/instances",
        json={
            "account_id": account_id,
            "name": "collector-task-priority",
            "instance_token": "token-task-priority",
            "status": "ready",
        },
    )
    instance_id = create_instance.json()["id"]

    old_hourly = client.post(
        "/api/v1/operator/tasks",
        json={
            "account_id": account_id,
            "collector_instance_id": instance_id,
            "task_type": "report_fetch_hourly",
            "report_date": "2026-07-05",
            "status": "pending",
            "external_request_id": "hourly-old",
        },
    )
    assert old_hourly.status_code == 201

    daily_task = client.post(
        "/api/v1/operator/tasks",
        json={
            "account_id": account_id,
            "collector_instance_id": instance_id,
            "task_type": "report_fetch",
            "report_date": "2026-07-05",
            "status": "pending",
            "external_request_id": "daily-middle",
        },
    )
    assert daily_task.status_code == 201

    latest_hourly = client.post(
        "/api/v1/operator/tasks",
        json={
            "account_id": account_id,
            "collector_instance_id": instance_id,
            "task_type": "report_fetch_hourly",
            "report_date": "2026-07-06",
            "status": "pending",
            "external_request_id": "hourly-latest",
        },
    )
    assert latest_hourly.status_code == 201

    response = client.get(
        "/api/v1/collector/tasks/next",
        headers={"Authorization": "Bearer token-task-priority"},
    )

    assert response.status_code == 200
    assert response.json()["id"] == latest_hourly.json()["id"]
    assert response.json()["task_type"] == "report_fetch_hourly"
    assert response.json()["report_date"] == "2026-07-06"


def test_targeted_recent_backfill_creates_tasks_for_target_accounts(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.collectors import service

    launched_instances: list[int] = []
    monkeypatch.setattr(service, "_launch_hourly_sync_runtime", lambda instance: launched_instances.append(instance.id))

    created_instance_ids: list[int] = []
    for account_key in ["lfmtmt", "bjsulide", "nnppw", "other"]:
        account = client.post(
            "/api/v1/operator/accounts",
            json={"name": f"account-{account_key}", "external_account_id": f"net-{account_key}", "status": "active"},
        )
        account_id = account.json()["id"]
        instance = client.post(
            "/api/v1/operator/instances",
            json={
                "account_id": account_id,
                "name": f"collector-{account_key}",
                "instance_token": f"token-{account_key}",
                "status": "ready",
                "report_base_url": f"https://{account_key}.example.com",
                "report_account_key": account_key,
                "report_token": f"token-{account_key}",
            },
        )
        if account_key != "other":
            created_instance_ids.append(instance.json()["id"])

    response = client.post(
        "/api/v1/operator/hourly-backfill/targeted-recent",
        json={"anchor_date": "2026-07-07", "days": 4},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["requested_account_keys"] == ["bjsulide", "lfmtmt", "nnppw"]
    assert body["days"] == 4
    assert len(body["items"]) == 12
    assert {item["account_key"] for item in body["items"]} == {"lfmtmt", "bjsulide", "nnppw"}
    assert {item["report_date"] for item in body["items"]} == {"2026-07-03", "2026-07-04", "2026-07-05", "2026-07-06"}
    assert all(item["hourly_sync_task_status"] == "pending" for item in body["items"])
    assert all(item["hourly_sync_task_created"] is True for item in body["items"])
    assert sorted(launched_instances) == sorted(created_instance_ids)


def test_operator_fetch_schedule_patch_rejects_cross_mode_update_without_mode(client: TestClient) -> None:
    create_account = client.post(
        "/api/v1/operator/accounts",
        json={"name": "account-fetch-cross", "external_account_id": "net-fetch-cross", "status": "active"},
    )
    account_id = create_account.json()["id"]

    create_instance = client.post(
        "/api/v1/operator/instances",
        json={
            "account_id": account_id,
            "name": "collector-fetch-cross",
            "instance_token": "token-fetch-cross",
            "status": "ready",
            "report_base_url": "https://node-fetch-cross.example.com",
            "report_account_key": "cross-account",
            "report_token": "cross-token",
        },
    )
    instance_id = create_instance.json()["id"]

    create_schedule = client.post(
        "/api/v1/operator/fetch-schedules",
        json={
            "account_id": account_id,
            "collector_instance_id": instance_id,
            "enabled": True,
            "mode": "daily_times",
            "daily_times": ["09:00", "21:00"],
            "interval_hours": None,
            "timezone": "Asia/Shanghai",
        },
    )
    schedule_id = create_schedule.json()["id"]

    patch_schedule = client.patch(
        f"/api/v1/operator/fetch-schedules/{schedule_id}",
        json={"interval_hours": 8},
    )
    assert patch_schedule.status_code == 422
    assert patch_schedule.json()["detail"] == "interval_hours update requires mode='interval_hours'"


def test_operator_fetch_schedule_patch_rejects_empty_daily_times_for_daily_mode(client: TestClient) -> None:
    create_account = client.post(
        "/api/v1/operator/accounts",
        json={"name": "account-fetch-empty-daily", "external_account_id": "net-fetch-empty-daily", "status": "active"},
    )
    account_id = create_account.json()["id"]

    create_instance = client.post(
        "/api/v1/operator/instances",
        json={
            "account_id": account_id,
            "name": "collector-fetch-empty-daily",
            "instance_token": "token-fetch-empty-daily",
            "status": "ready",
            "report_base_url": "https://node-fetch-empty-daily.example.com",
            "report_account_key": "empty-daily-account",
            "report_token": "empty-daily-token",
        },
    )
    instance_id = create_instance.json()["id"]

    create_schedule = client.post(
        "/api/v1/operator/fetch-schedules",
        json={
            "account_id": account_id,
            "collector_instance_id": instance_id,
            "enabled": True,
            "mode": "daily_times",
            "daily_times": ["09:00", "21:00"],
            "interval_hours": None,
            "timezone": "Asia/Shanghai",
        },
    )
    schedule_id = create_schedule.json()["id"]

    patch_schedule = client.patch(
        f"/api/v1/operator/fetch-schedules/{schedule_id}",
        json={"daily_times": []},
    )
    assert patch_schedule.status_code == 422


def test_operator_fetch_schedule_create_rejects_duplicate_schedule(client: TestClient) -> None:
    create_account = client.post(
        "/api/v1/operator/accounts",
        json={"name": "account-fetch-duplicate", "external_account_id": "net-fetch-duplicate", "status": "active"},
    )
    account_id = create_account.json()["id"]

    create_instance = client.post(
        "/api/v1/operator/instances",
        json={
            "account_id": account_id,
            "name": "collector-fetch-duplicate",
            "instance_token": "token-fetch-duplicate",
            "status": "ready",
            "report_base_url": "https://node-fetch-duplicate.example.com",
            "report_account_key": "dup-account",
            "report_token": "dup-token",
        },
    )
    instance_id = create_instance.json()["id"]

    payload = {
        "account_id": account_id,
        "collector_instance_id": instance_id,
        "enabled": True,
        "mode": "daily_times",
        "daily_times": ["09:00", "21:00"],
        "interval_hours": None,
        "timezone": "Asia/Shanghai",
    }

    first_response = client.post("/api/v1/operator/fetch-schedules", json=payload)
    assert first_response.status_code == 201

    second_response = client.post("/api/v1/operator/fetch-schedules", json=payload)
    assert second_response.status_code == 409
    assert second_response.json()["detail"] == "Fetch schedule already exists for this collector instance"


def test_operator_fetch_schedule_create_rejects_account_instance_mismatch(client: TestClient) -> None:
    first_account = client.post(
        "/api/v1/operator/accounts",
        json={"name": "account-fetch-mismatch-a", "external_account_id": "net-fetch-mismatch-a", "status": "active"},
    ).json()
    second_account = client.post(
        "/api/v1/operator/accounts",
        json={"name": "account-fetch-mismatch-b", "external_account_id": "net-fetch-mismatch-b", "status": "active"},
    ).json()

    create_instance = client.post(
        "/api/v1/operator/instances",
        json={
            "account_id": first_account["id"],
            "name": "collector-fetch-mismatch",
            "instance_token": "token-fetch-mismatch",
            "status": "ready",
            "report_base_url": "https://node-fetch-mismatch.example.com",
            "report_account_key": "mismatch-account",
            "report_token": "mismatch-token",
        },
    )
    instance_id = create_instance.json()["id"]

    response = client.post(
        "/api/v1/operator/fetch-schedules",
        json={
            "account_id": second_account["id"],
            "collector_instance_id": instance_id,
            "enabled": True,
            "mode": "daily_times",
            "daily_times": ["09:00", "21:00"],
            "interval_hours": None,
            "timezone": "Asia/Shanghai",
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Collector instance account does not match fetch schedule account"


def test_manual_fetch_rejects_remote_ok_false(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.collectors import service

    create_account = client.post(
        "/api/v1/operator/accounts",
        json={"name": "account-manual-remote-fail", "external_account_id": "net-manual-remote-fail", "status": "active"},
    )
    account_id = create_account.json()["id"]

    create_instance = client.post(
        "/api/v1/operator/instances",
        json={
            "account_id": account_id,
            "name": "collector-manual-remote-fail",
            "instance_token": "token-manual-remote-fail",
            "status": "ready",
            "report_base_url": "https://node-remote-fail.example.com",
            "report_account_key": "jwtnx",
            "report_token": "token-jwtnx",
        },
    )
    instance_id = create_instance.json()["id"]

    def fake_get(url: str, params: dict[str, str], timeout: int) -> DummyHttpxResponse:
        return DummyHttpxResponse(
            200,
            {
                "ok": False,
                "status": "failed",
                "request_id": "req-failed",
                "message": "remote rejected request",
            },
        )

    monkeypatch.setattr(service.httpx, "get", fake_get)

    response = client.post(
        "/api/v1/operator/fetch-schedules/manual-fetch",
        json={
            "account_id": account_id,
            "collector_instance_id": instance_id,
            "report_date": "2026-06-23",
        },
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "remote rejected request"


def test_manual_fetch_rejects_remote_non_200(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.collectors import service

    create_account = client.post(
        "/api/v1/operator/accounts",
        json={"name": "account-manual-remote-http", "external_account_id": "net-manual-remote-http", "status": "active"},
    )
    account_id = create_account.json()["id"]

    create_instance = client.post(
        "/api/v1/operator/instances",
        json={
            "account_id": account_id,
            "name": "collector-manual-remote-http",
            "instance_token": "token-manual-remote-http",
            "status": "ready",
            "report_base_url": "https://node-remote-http.example.com",
            "report_account_key": "jwtnx",
            "report_token": "token-jwtnx",
        },
    )
    instance_id = create_instance.json()["id"]

    def fake_get(url: str, params: dict[str, str], timeout: int) -> DummyHttpxResponse:
        return DummyHttpxResponse(503, {"ok": False, "message": "service unavailable"})

    monkeypatch.setattr(service.httpx, "get", fake_get)

    response = client.post(
        "/api/v1/operator/fetch-schedules/manual-fetch",
        json={
            "account_id": account_id,
            "collector_instance_id": instance_id,
            "report_date": "2026-06-23",
        },
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "Remote fetch returned HTTP 503"


def test_manual_fetch_rejects_remote_invalid_json(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.collectors import service

    create_account = client.post(
        "/api/v1/operator/accounts",
        json={"name": "account-manual-invalid-json", "external_account_id": "net-manual-invalid-json", "status": "active"},
    )
    account_id = create_account.json()["id"]

    create_instance = client.post(
        "/api/v1/operator/instances",
        json={
            "account_id": account_id,
            "name": "collector-manual-invalid-json",
            "instance_token": "token-manual-invalid-json",
            "status": "ready",
            "report_base_url": "https://node-invalid-json.example.com",
            "report_account_key": "jwtnx",
            "report_token": "token-jwtnx",
        },
    )
    instance_id = create_instance.json()["id"]

    class InvalidJsonResponse(DummyHttpxResponse):
        def json(self) -> dict[str, object]:
            raise ValueError("bad json")

    def fake_get(url: str, params: dict[str, str], timeout: int) -> DummyHttpxResponse:
        return InvalidJsonResponse(200, {})

    monkeypatch.setattr(service.httpx, "get", fake_get)

    response = client.post(
        "/api/v1/operator/fetch-schedules/manual-fetch",
        json={
            "account_id": account_id,
            "collector_instance_id": instance_id,
            "report_date": "2026-06-23",
        },
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "Remote fetch returned invalid JSON"


def test_operator_can_generate_mid_platform_hourly_reports(client: TestClient) -> None:
    create_account = client.post(
        "/api/v1/operator/accounts",
        json={"name": "account-hourly", "external_account_id": "ext-hourly", "status": "active"},
    )
    account_id = create_account.json()["id"]

    create_instance = client.post(
        "/api/v1/operator/instances",
        json={
            "account_id": account_id,
            "name": "collector-hourly",
            "instance_token": "token-hourly",
            "status": "ready",
            "report_base_url": "https://node-hourly.example.com",
            "report_account_key": "a-hourly",
            "report_token": "token-hourly",
        },
    )
    assert create_instance.status_code == 201

    db: Session = client.app.dependency_overrides[get_db]().__next__()
    try:
        db.add(
            AccountHourlyReport(
                account_id=account_id,
                report_date=date(2026, 5, 16),
                hour=9,
                report_time_utc=datetime(2026, 5, 16, 16, 0, tzinfo=timezone.utc),
                source_timezone="America/Los_Angeles",
                currency="USD",
                ad_country_code="US",
                ad_country_name="United States",
                ad_slot_id="slot-top",
                ad_slot_name="Top Banner",
                responses_served=12,
                impressions=10,
                clicks=1,
                revenue=Decimal("1.200000"),
                ecpm=Decimal("120.000000"),
            )
        )
        db.add(
            SiteHourlyReport(
                account_id=account_id,
                report_date=date(2026, 5, 16),
                hour=9,
                report_time_utc=datetime(2026, 5, 16, 16, 0, tzinfo=timezone.utc),
                source_timezone="America/Los_Angeles",
                currency="USD",
                url_id="url-hourly-1",
                url="hourly.example.com",
                ad_country_code="US",
                ad_country_name="United States",
                ad_slot_id="slot-top",
                ad_slot_name="Top Banner",
                responses_served=12,
                impressions=10,
                clicks=1,
                revenue=Decimal("1.200000"),
                ecpm=Decimal("120.000000"),
            )
        )
        db.commit()
    finally:
        db.close()

    account_response = client.get("/api/v1/operator/mid-platform/reports/account-hourly", params={"report_date": "2026-05-16"})
    assert account_response.status_code == 200
    assert account_response.json()["timezone"] == "America/Los_Angeles"
    assert account_response.json()["items"] == [
        {
            "account_id": account_id,
            "account_name": "account-hourly",
            "instance_id": 1,
            "instance_name": "collector-hourly",
            "node_base_url": "https://node-hourly.example.com",
            "node_account_key": "a-hourly",
            "report_date": "2026-05-16",
            "hour": 9,
            "report_time_utc": "2026-05-16T16:00:00Z",
            "source_timezone": "America/Los_Angeles",
            "currency": "USD",
            "ad_country_code": "US",
            "ad_country_name": "United States",
            "ad_slot_id": "slot-top",
            "ad_slot_name": "Top Banner",
            "responses_served": 12,
            "requests": 0,
            "impressions": 10,
            "clicks": 1,
            "revenue": 1.2,
            "ecpm": 120.0,
            "source_run_id": None,
        }
    ]

    site_response = client.get("/api/v1/operator/mid-platform/reports/site-hourly", params={"report_date": "2026-05-16"})
    assert site_response.status_code == 200
    assert site_response.json()["timezone"] == "America/Los_Angeles"
    assert site_response.json()["items"] == [
        {
            "account_id": account_id,
            "account_name": "account-hourly",
            "instance_id": 1,
            "instance_name": "collector-hourly",
            "node_base_url": "https://node-hourly.example.com",
            "node_account_key": "a-hourly",
            "report_date": "2026-05-16",
            "hour": 9,
            "report_time_utc": "2026-05-16T16:00:00Z",
            "source_timezone": "America/Los_Angeles",
            "currency": "USD",
            "site_name": "hourly.example.com",
            "ad_country_code": "US",
            "ad_country_name": "United States",
            "ad_slot_id": "slot-top",
            "ad_slot_name": "Top Banner",
            "responses_served": 12,
            "requests": 0,
            "impressions": 10,
            "clicks": 1,
            "revenue": 1.2,
            "ecpm": 120.0,
            "source_run_id": None,
        }
    ]
