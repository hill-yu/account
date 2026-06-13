from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from app.vps_service import VpsFetchResult, VpsSiteDailyReportResult


class FakeFetchService:
    def enqueue_fetch(self, *, account_key, report_date, trigger_source, request_id):
        assert account_key == "a1"
        assert report_date == date(2026, 6, 3)
        assert trigger_source == "php_manual"
        assert request_id == "req-001"
        return VpsFetchResult(
            run_id=17,
            account_key=account_key,
            report_date=report_date.isoformat(),
            row_count=0,
            status="accepted",
        )

    def get_site_daily_report(self, *, account_key, report_date):
        assert account_key == "a1"
        assert report_date == date(2026, 6, 3)
        return VpsSiteDailyReportResult(
            account_key=account_key,
            report_date=report_date.isoformat(),
            has_run=True,
            run_status="success",
            run_id=17,
            row_count=2,
            error_message=None,
            items=[
                {
                    "site_name": "jane.ghfkl.com",
                    "responses_served": 34,
                    "impressions": 33,
                    "clicks": 4,
                    "revenue": "7.646800",
                    "ecpm": "231.721203",
                },
                {
                    "site_name": "longan.ghfkl.com",
                    "responses_served": 53,
                    "impressions": 51,
                    "clicks": 4,
                    "revenue": "8.871416",
                    "ecpm": "173.949341",
                },
            ],
        )


def test_internal_fetch_endpoint_returns_accepted_payload() -> None:
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
        "row_count": 0,
        "status": "accepted",
    }


def test_internal_fetch_endpoint_maps_account_config_errors_to_422() -> None:
    from app.vps_api import create_app
    from app.vps_service import AccountConfigError

    class FailingFetchService:
        def enqueue_fetch(self, *, account_key, report_date, trigger_source, request_id):
            raise AccountConfigError("Unknown active account_key: bad")

        def get_site_daily_report(self, *, account_key, report_date):
            raise AssertionError("not used")

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
        def enqueue_fetch(self, *, account_key, report_date, trigger_source, request_id):
            raise FetchExecutionError("upstream fetch failed")

        def get_site_daily_report(self, *, account_key, report_date):
            raise AssertionError("not used")

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
        def enqueue_fetch(self, *, account_key, report_date, trigger_source, request_id):
            raise FetchExecutionError(
                "Fetch already queued or running for account_key=a1 report_date=2026-06-03 (run_id=17, request_id=req-001)"
            )

        def get_site_daily_report(self, *, account_key, report_date):
            raise AssertionError("not used")

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
        "detail": "Fetch already queued or running for account_key=a1 report_date=2026-06-03 (run_id=17, request_id=req-001)"
    }


def test_internal_site_daily_endpoint_returns_report_payload() -> None:
    from app.vps_api import create_app

    app = create_app(fetch_service=FakeFetchService())
    client = TestClient(app)

    response = client.get(
        "/internal/reports/site-daily",
        params={
            "account_key": "a1",
            "report_date": "2026-06-03",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "account_key": "a1",
        "report_date": "2026-06-03",
        "has_run": True,
        "run_status": "success",
        "run_id": 17,
        "row_count": 2,
        "error_message": None,
        "items": [
            {
                "site_name": "jane.ghfkl.com",
                "responses_served": 34,
                "impressions": 33,
                "clicks": 4,
                "revenue": "7.646800",
                "ecpm": "231.721203",
            },
            {
                "site_name": "longan.ghfkl.com",
                "responses_served": 53,
                "impressions": 51,
                "clicks": 4,
                "revenue": "8.871416",
                "ecpm": "173.949341",
            },
        ],
    }


def test_internal_site_daily_endpoint_returns_success_snapshot_fields() -> None:
    from app.vps_api import create_app

    class FakeFetchService:
        def enqueue_fetch(self, *, account_key, report_date, trigger_source, request_id):
            raise AssertionError("not used")

        def get_site_daily_report(self, *, account_key, report_date):
            return VpsSiteDailyReportResult(
                account_key=account_key,
                report_date=report_date.isoformat(),
                has_run=True,
                run_status="success",
                run_id=17,
                row_count=1,
                error_message=None,
                items=[
                    {
                        "site_name": "jane.ghfkl.com",
                        "responses_served": 34,
                        "impressions": 33,
                        "clicks": 4,
                        "revenue": "7.646800",
                        "ecpm": "231.721203",
                    }
                ],
            )

    app = create_app(fetch_service=FakeFetchService())
    client = TestClient(app)
    response = client.get(
        "/internal/reports/site-daily",
        params={"account_key": "a1", "report_date": "2026-06-03"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "account_key": "a1",
        "report_date": "2026-06-03",
        "has_run": True,
        "run_status": "success",
        "run_id": 17,
        "row_count": 1,
        "error_message": None,
        "items": [
            {
                "site_name": "jane.ghfkl.com",
                "responses_served": 34,
                "impressions": 33,
                "clicks": 4,
                "revenue": "7.646800",
                "ecpm": "231.721203",
            }
        ],
    }


def test_internal_site_daily_endpoint_returns_not_started_shape() -> None:
    from app.vps_api import create_app

    class FakeFetchService:
        def enqueue_fetch(self, *, account_key, report_date, trigger_source, request_id):
            raise AssertionError("not used")

        def get_site_daily_report(self, *, account_key, report_date):
            return VpsSiteDailyReportResult(
                account_key=account_key,
                report_date=report_date.isoformat(),
                has_run=False,
                run_status=None,
                run_id=None,
                row_count=0,
                error_message=None,
                items=[],
            )

    app = create_app(fetch_service=FakeFetchService())
    client = TestClient(app)

    response = client.get(
        "/internal/reports/site-daily",
        params={
            "account_key": "a1",
            "report_date": "2026-06-03",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "account_key": "a1",
        "report_date": "2026-06-03",
        "has_run": False,
        "run_status": None,
        "run_id": None,
        "row_count": 0,
        "error_message": None,
        "items": [],
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


def test_public_fetch_endpoint_returns_php_compatible_payload(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("ADX_TRIGGER_TOKEN", "public-token")

    from app.vps_config import get_vps_settings
    from app.vps_api import create_app

    class PublicFetchService:
        def enqueue_fetch(self, *, account_key, report_date, trigger_source, request_id):
            assert account_key == "a1"
            assert report_date == date(2026, 6, 3)
            assert trigger_source == "php_manual"
            assert request_id.startswith("req_")
            return VpsFetchResult(
                run_id=17,
                account_key=account_key,
                report_date=report_date.isoformat(),
                row_count=0,
                status="accepted",
            )

        def get_site_daily_report(self, *, account_key, report_date):
            raise AssertionError("not used")

    get_vps_settings.cache_clear()
    app = create_app(fetch_service=PublicFetchService())
    client = TestClient(app)

    response = client.get(
        "/public/fetch.php",
        params={
            "token": "public-token",
            "account_key": "a1",
            "report_date": "2026-06-03",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["status"] == "accepted"
    assert payload["account_key"] == "a1"
    assert payload["report_date"] == "2026-06-03"
    assert payload["row_count"] == 0
    assert payload["run_id"] == 17
    assert payload["request_id"].startswith("req_")


def test_public_report_endpoint_rejects_invalid_token(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("ADX_TRIGGER_TOKEN", "public-token")

    from app.vps_config import get_vps_settings
    from app.vps_api import create_app

    get_vps_settings.cache_clear()
    app = create_app(fetch_service=FakeFetchService())
    client = TestClient(app)

    response = client.get(
        "/public/report.php",
        params={
            "token": "wrong-token",
            "account_key": "a1",
            "report_date": "2026-06-03",
        },
    )

    assert response.status_code == 401
    payload = response.json()
    assert payload == {
        "ok": False,
        "error_code": "REQUEST_ERROR",
        "message": "invalid token",
        "request_id": payload["request_id"],
    }
