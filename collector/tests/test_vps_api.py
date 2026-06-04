from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from app.vps_service import VpsFetchResult


class FakeFetchService:
    def run_fetch(self, *, account_key, report_date, trigger_source, request_id):
        assert account_key == "a1"
        assert report_date == date(2026, 6, 3)
        assert trigger_source == "php_manual"
        assert request_id == "req-001"
        return VpsFetchResult(
            run_id=17,
            account_key=account_key,
            report_date=report_date.isoformat(),
            row_count=8,
            status="success",
        )


def test_internal_fetch_endpoint_returns_success_payload() -> None:
    from app.vps_api import create_app

    app = create_app(fetch_service=FakeFetchService())
    client = TestClient(app)

    response = client.post(
        "/internal/fetch",
        json={
            "account_key": "a1",
            "report_date": "2026-06-03",
            "trigger_source": "php_manual",
            "request_id": "req-001",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "run_id": 17,
        "account_key": "a1",
        "report_date": "2026-06-03",
        "row_count": 8,
        "status": "success",
    }


def test_internal_fetch_endpoint_maps_account_config_errors_to_422() -> None:
    from app.vps_api import create_app
    from app.vps_service import AccountConfigError

    class FailingFetchService:
        def run_fetch(self, *, account_key, report_date, trigger_source, request_id):
            raise AccountConfigError("Unknown active account_key: bad")

    app = create_app(fetch_service=FailingFetchService())
    client = TestClient(app)

    response = client.post(
        "/internal/fetch",
        json={
            "account_key": "bad",
            "report_date": "2026-06-03",
            "trigger_source": "php_manual",
            "request_id": "req-002",
        },
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Unknown active account_key: bad"}


def test_internal_fetch_endpoint_maps_fetch_execution_errors_to_502() -> None:
    from app.vps_api import create_app
    from app.vps_service import FetchExecutionError

    class FailingFetchService:
        def run_fetch(self, *, account_key, report_date, trigger_source, request_id):
            raise FetchExecutionError("upstream fetch failed")

    app = create_app(fetch_service=FailingFetchService())
    client = TestClient(app)

    response = client.post(
        "/internal/fetch",
        json={
            "account_key": "a1",
            "report_date": "2026-06-03",
            "trigger_source": "php_manual",
            "request_id": "req-003",
        },
    )

    assert response.status_code == 502
    assert response.json() == {"detail": "upstream fetch failed"}


def test_internal_fetch_endpoint_maps_fetch_conflicts_to_409() -> None:
    from app.vps_api import create_app
    from app.vps_service import FetchExecutionError

    class ConflictingFetchService:
        def run_fetch(self, *, account_key, report_date, trigger_source, request_id):
            raise FetchExecutionError(
                "Fetch already running for account_key=a1 report_date=2026-06-03 (run_id=17, request_id=req-001)"
            )

    app = create_app(fetch_service=ConflictingFetchService())
    client = TestClient(app)

    response = client.post(
        "/internal/fetch",
        json={
            "account_key": "a1",
            "report_date": "2026-06-03",
            "trigger_source": "php_manual",
            "request_id": "req-004",
        },
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Fetch already running for account_key=a1 report_date=2026-06-03 (run_id=17, request_id=req-001)"
    }


def test_internal_fetch_endpoint_rejects_overlong_request_fields() -> None:
    from app.vps_api import create_app

    app = create_app(fetch_service=FakeFetchService())
    client = TestClient(app)

    response = client.post(
        "/internal/fetch",
        json={
            "account_key": "a" * 101,
            "report_date": "2026-06-03",
            "trigger_source": "p" * 65,
            "request_id": "r" * 101,
        },
    )

    assert response.status_code == 422
    errors = response.json()["detail"]

    assert [error["loc"] for error in errors] == [
        ["body", "account_key"],
        ["body", "trigger_source"],
        ["body", "request_id"],
    ]
