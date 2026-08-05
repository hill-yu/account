from __future__ import annotations

from collections.abc import Generator
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app import models as _models  # noqa: F401
from app.database import Base, get_db
from app.main import create_app
from app.models.account_daily_report import AccountDailyReport
from app.models.account_hourly_report import AccountHourlyReport
from app.models.site_daily_report import SiteDailyReport
from app.models.site_hourly_report import SiteHourlyReport
from app.models.collector_ingestion_batch import CollectorIngestionBatch
from app.models.site_daily_dimension_report import SiteDailyDimensionReport
from app.models.authoritative_daily_version_summary import AuthoritativeDailyVersionSummary
from app.collectors.service import _beijing_date_range_utc


@pytest.fixture()
def client(tmp_path: Path) -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    database_path = tmp_path / "ingestion-service.db"
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
        test_client.headers.update({"X-ADX-Operator-Token": "test-operator-token"})
        yield test_client, session_factory

    app.dependency_overrides.clear()
    engine.dispose()


def _seed_task(client: TestClient) -> tuple[int, str]:
    create_account = client.post(
        "/api/v1/operator/accounts",
        json={"name": "account-ingestion", "external_account_id": "ext-ingestion", "status": "active"},
    )
    account_id = create_account.json()["id"]

    create_instance = client.post(
        "/api/v1/operator/instances",
        json={
            "account_id": account_id,
            "name": "collector-ingestion",
            "instance_token": "token-ingestion",
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
    return create_task.json()["id"], "token-ingestion"


def _hash_rows(rows: list[dict[str, object]]) -> str:
    return hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def test_batch_ingestion_is_idempotent_by_task_and_batch_key(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client
    task_id, token = _seed_task(test_client)
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "batch_key": "page-1",
        "row_count": 1,
        "payload_hash": "hash-1",
        "schema_version": "admanager_site_core_v1",
            "rows": [
                {
                    "report_date": "2026-05-21",
                    "url_id": "123",
                    "url": "https://example.com/home",
                    "responses_served": 8,
                    "requests": 10,
                    "impressions": 5,
                    "clicks": 1,
                    "revenue": "0.250000",
                "ecpm": "50.000000",
            }
        ],
    }

    first = test_client.post(f"/api/v1/collector/tasks/{task_id}/batches", headers=headers, json=payload)
    assert first.status_code == 201
    first_body = first.json()
    assert first_body["duplicate"] is False

    second = test_client.post(f"/api/v1/collector/tasks/{task_id}/batches", headers=headers, json=payload)
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["duplicate"] is True
    assert second_body["id"] == first_body["id"]

    with session_factory() as session:
        batches = session.scalars(select(CollectorIngestionBatch)).all()

    assert len(batches) == 1
    assert batches[0].task_id == task_id
    assert batches[0].batch_key == "page-1"
    assert batches[0].schema_version == "admanager_site_core_v1"
    assert batches[0].payload_json == json.dumps(payload["rows"], separators=(",", ":"), sort_keys=True)

    with session_factory() as session:
        site_rows = session.scalars(select(SiteDailyReport)).all()
        account_rows = session.scalars(select(AccountDailyReport)).all()

    assert len(site_rows) == 1
    assert site_rows[0].url_id == "123"
    assert site_rows[0].impressions == 5
    assert site_rows[0].requests == 10
    assert len(account_rows) == 1
    assert account_rows[0].responses_served == 8
    assert account_rows[0].requests == 10
    assert account_rows[0].impressions == 5


def test_batch_ingestion_rejects_invalid_instance_token(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, _ = client
    task_id, _ = _seed_task(test_client)

    response = test_client.post(
        f"/api/v1/collector/tasks/{task_id}/batches",
        headers={"Authorization": "Bearer invalid-token"},
        json={"batch_key": "page-1", "row_count": 5, "payload_hash": "hash-1", "schema_version": "admanager_site_core_v1"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid collector token"


def test_batch_ingestion_returns_409_for_conflicting_reuse_of_batch_key(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, _ = client
    task_id, token = _seed_task(test_client)
    headers = {"Authorization": f"Bearer {token}"}

    first = test_client.post(
        f"/api/v1/collector/tasks/{task_id}/batches",
        headers=headers,
        json={"batch_key": "page-1", "row_count": 5, "payload_hash": "hash-1", "schema_version": "admanager_site_core_v1"},
    )
    assert first.status_code == 201

    conflicting = test_client.post(
        f"/api/v1/collector/tasks/{task_id}/batches",
        headers=headers,
        json={"batch_key": "page-1", "row_count": 6, "payload_hash": "hash-2", "schema_version": "admanager_site_core_v1"},
    )
    assert conflicting.status_code == 409


def test_operator_report_endpoints_return_projected_rows(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, _ = client
    task_id, token = _seed_task(test_client)
    headers = {"Authorization": f"Bearer {token}"}

    ingest = test_client.post(
        f"/api/v1/collector/tasks/{task_id}/batches",
        headers=headers,
        json={
            "batch_key": "page-1",
            "row_count": 2,
            "payload_hash": "hash-report-1",
            "schema_version": "admanager_site_core_v1",
            "rows": [
                {
                    "report_date": "2026-05-21",
                    "url_id": "url-1",
                    "url": "https://example.com/a",
                    "responses_served": 100,
                    "requests": 130,
                    "impressions": 90,
                    "clicks": 3,
                    "revenue": "1.500000",
                    "ecpm": "16.666667",
                },
                {
                    "report_date": "2026-05-21",
                    "url_id": "url-2",
                    "url": "https://example.com/b",
                    "responses_served": 60,
                    "requests": 72,
                    "impressions": 50,
                    "clicks": 1,
                    "revenue": "0.500000",
                    "ecpm": "10.000000",
                },
            ],
        },
    )
    assert ingest.status_code == 201

    sites = test_client.get("/api/v1/operator/reports/site-daily", params={"account_id": 1, "report_date": "2026-05-21"})
    assert sites.status_code == 200
    assert sites.json()["timezone"] == "America/Los_Angeles"
    assert len(sites.json()["items"]) == 2
    assert sites.json()["items"][0]["url"] == "https://example.com/a"

    account_daily = test_client.get("/api/v1/operator/reports/account-daily", params={"account_id": 1, "report_date": "2026-05-21"})
    assert account_daily.status_code == 200
    assert account_daily.json()["timezone"] == "America/Los_Angeles"
    assert account_daily.json()["coverage"] is None
    assert account_daily.json()["items"][0]["responses_served"] == 160
    assert account_daily.json()["items"][0]["requests"] == 202
    assert account_daily.json()["items"][0]["impressions"] == 140
    assert account_daily.json()["items"][0]["clicks"] == 4
    assert account_daily.json()["items"][0]["revenue"] == 2.0


def test_hourly_dimension_batch_projects_hourly_facts_without_overwriting_authoritative_daily(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client
    task_id, token = _seed_task(test_client)
    headers = {"Authorization": f"Bearer {token}"}

    with session_factory() as session:
        session.add(
            SiteDailyReport(
                account_id=1,
                report_date=date(2026, 5, 21),
                url_id="authoritative-url",
                url="https://authoritative.example.com",
                responses_served=999,
                requests=1000,
                impressions=900,
                clicks=90,
                revenue=Decimal("9.000000"),
                ecpm=Decimal("10.000000"),
            )
        )
        session.add(
            AccountDailyReport(
                account_id=1,
                report_date=date(2026, 5, 21),
                responses_served=999,
                requests=1000,
                impressions=900,
                clicks=90,
                revenue=Decimal("9.000000"),
                ecpm=Decimal("10.000000"),
            )
        )
        session.commit()

    ingest = test_client.post(
        f"/api/v1/collector/tasks/{task_id}/batches",
        headers=headers,
        json={
            "batch_key": "page-hourly-1",
            "row_count": 2,
            "payload_hash": "hash-hourly-1",
            "schema_version": "admanager_hourly_dimension_v1",
            "rows": [
                {
                    "report_date": "2026-05-21",
                    "hour": 9,
                    "report_time_utc": "2026-05-21T16:00:00Z",
                    "source_timezone": "America/Los_Angeles",
                    "currency": "USD",
                    "url_id": "url-1",
                    "url": "https://example.com/a",
                    "ad_country_code": "US",
                    "ad_country_name": "United States",
                    "ad_slot_id": "slot-top",
                    "ad_slot_name": "Top Banner",
                    "responses_served": 100,
                    "requests": 130,
                    "impressions": 80,
                    "clicks": 4,
                    "revenue": "1.600000",
                },
                {
                    "report_date": "2026-05-21",
                    "hour": 9,
                    "report_time_utc": "2026-05-21T16:00:00Z",
                    "source_timezone": "America/Los_Angeles",
                    "currency": "USD",
                    "url_id": "url-2",
                    "url": "https://example.com/b",
                    "ad_country_code": "US",
                    "ad_country_name": "United States",
                    "ad_slot_id": "slot-top",
                    "ad_slot_name": "Top Banner",
                    "responses_served": 40,
                    "requests": 60,
                    "impressions": 20,
                    "clicks": 1,
                    "revenue": "0.400000",
                },
            ],
        },
    )
    assert ingest.status_code == 201

    with session_factory() as session:
        site_hourly_rows = session.scalars(select(SiteHourlyReport).order_by(SiteHourlyReport.url_id)).all()
        account_hourly_rows = session.scalars(select(AccountHourlyReport)).all()
        site_daily_rows = session.scalars(select(SiteDailyReport).order_by(SiteDailyReport.url_id)).all()
        account_daily_rows = session.scalars(select(AccountDailyReport)).all()

    assert len(site_hourly_rows) == 2
    assert site_hourly_rows[0].report_time_utc == datetime(2026, 5, 21, 16, 0)
    assert site_hourly_rows[0].ad_country_code == "US"
    assert site_hourly_rows[0].ad_slot_id == "slot-top"
    assert site_hourly_rows[0].requests == 130

    assert len(account_hourly_rows) == 1
    assert account_hourly_rows[0].responses_served == 140
    assert account_hourly_rows[0].requests == 190
    assert account_hourly_rows[0].impressions == 100
    assert account_hourly_rows[0].revenue == 2
    assert account_hourly_rows[0].report_time_utc == datetime(2026, 5, 21, 16, 0)

    assert len(site_daily_rows) == 1
    assert site_daily_rows[0].url_id == "authoritative-url"
    assert len(account_daily_rows) == 1
    assert account_daily_rows[0].responses_served == 999
    assert account_daily_rows[0].requests == 1000
    assert account_daily_rows[0].impressions == 900
    assert account_daily_rows[0].clicks == 90
    assert account_daily_rows[0].revenue == 9

    site_daily = test_client.get("/api/v1/operator/reports/site-daily", params={"account_id": 1, "report_date": "2026-05-21"})
    assert site_daily.status_code == 200
    assert site_daily.json()["coverage"] == {
        "account_id": 1,
        "report_date": "2026-05-21",
        "hours_present": [9],
        "hour_count": 1,
        "min_hour": 9,
        "max_hour": 9,
        "is_complete_day": False,
        "latest_task_id": 1,
        "daily_revenue": 9.0,
        "hourly_revenue": 2.0,
        "revenue_diff_percent": 77.78,
        "daily_impressions": 900,
        "hourly_impressions": 100,
        "impressions_diff_percent": 88.89,
        "is_value_match": False,
    }

    account_daily = test_client.get(
        "/api/v1/operator/reports/account-daily",
        params={"account_id": 1, "report_date": "2026-05-21"},
    )
    assert account_daily.status_code == 200
    assert account_daily.json()["coverage"]["hours_present"] == [9]
    assert account_daily.json()["coverage"]["is_complete_day"] is False

    dimensions = test_client.get(
        "/api/v1/operator/mid-platform/reports/site-hourly-dimensions",
        params={"account_id": 1, "report_date": "2026-05-22", "site_name": "https://example.com/a", "page": 1, "page_size": 1},
    )
    assert dimensions.status_code == 200
    dimension_body = dimensions.json()
    assert dimension_body["dimension_data_available"] is False
    assert dimension_body["available_from"] == "2026-08-02"
    assert dimension_body["page"] == 1
    assert dimension_body["page_size"] == 1
    assert dimension_body["total"] == 1
    assert dimension_body["items"][0]["report_date"] == "2026-05-22"
    assert dimension_body["items"][0]["hour"] == 0
    assert dimension_body["items"][0]["report_time_utc"] == "2026-05-21T16:00:00"
    assert dimension_body["items"][0]["source_timezone"] == "America/Los_Angeles"

    date_range = test_client.get(
        "/api/v1/operator/mid-platform/reports/site-hourly-dimensions",
        params={"account_id": 1, "start_date": "2026-05-22", "end_date": "2026-05-22"},
    )
    assert date_range.status_code == 200
    assert date_range.json()["report_date"] == "2026-05-22"
    assert date_range.json()["start_date"] == "2026-05-22"
    assert date_range.json()["end_date"] == "2026-05-22"
    assert date_range.json()["total"] == 2

    second_page = test_client.get(
        "/api/v1/operator/mid-platform/reports/site-hourly-dimensions",
        params={"account_id": 1, "report_date": "2026-05-22", "page": 2, "page_size": 1},
    )
    assert second_page.status_code == 200
    assert second_page.json()["total"] == 2
    assert [item["site_name"] for item in second_page.json()["items"]] == ["https://example.com/b"]

    invalid_range = test_client.get(
        "/api/v1/operator/mid-platform/reports/site-hourly-dimensions",
        params={"start_date": "2026-05-01", "end_date": "2026-06-01"},
    )
    assert invalid_range.status_code == 422

    ambiguous_range = test_client.get(
        "/api/v1/operator/mid-platform/reports/site-hourly-dimensions",
        params={"report_date": "2026-05-21", "start_date": "2026-05-21", "end_date": "2026-05-21"},
    )
    assert ambiguous_range.status_code == 422

    daily_dimensions = test_client.post(
        f"/api/v1/collector/tasks/{task_id}/batches",
        headers=headers,
        json={
            "batch_key": "daily-dimension-page-1",
            "row_count": 1,
            "payload_hash": "daily-dimension-hash-1",
            "schema_version": "admanager_daily_dimension_v1",
            "rows": [{"report_date": "2026-05-21", "url_id": "url-1", "url": "https://example.com/a", "ad_country_code": "US", "ad_country_name": "United States", "ad_slot_id": "slot-top", "ad_slot_name": "Top Banner", "responses_served": 100, "requests": 130, "impressions": 80, "clicks": 4, "revenue": "1.600000", "ecpm": "20.000000"}],
        },
    )
    assert daily_dimensions.status_code == 201

    daily_dimension_response = test_client.get(
        "/api/v1/operator/mid-platform/reports/site-daily-dimensions",
        params={"account_id": 1, "report_date": "2026-05-21", "ad_country_code": "US", "ad_slot_id": "slot-top"},
    )
    assert daily_dimension_response.status_code == 200
    daily_item = daily_dimension_response.json()["items"][0]
    assert daily_item["source_kind"] == "authoritative_daily"
    assert daily_item["is_finalized"] is True
    assert daily_item["coverage_rate"] == pytest.approx(100 / 130)
    assert daily_item["click_through_rate"] == pytest.approx(4 / 80)
    assert daily_item["impression_rate"] == pytest.approx(80 / 100)

    assert "is_finalized" not in dimensions.json()["items"][0]

    account_daily_dimension_response = test_client.get(
        "/api/v1/operator/mid-platform/reports/account-daily-dimensions",
        params={"account_id": 1, "report_date": "2026-05-21", "ad_country_code": "US", "ad_slot_id": "slot-top"},
    )
    assert account_daily_dimension_response.status_code == 200
    assert account_daily_dimension_response.json()["items"][0]["is_finalized"] is True

    zero_denominator = test_client.post(
        f"/api/v1/collector/tasks/{task_id}/batches",
        headers=headers,
        json={
            "batch_key": "daily-dimension-page-2",
            "row_count": 1,
            "payload_hash": "daily-dimension-hash-2",
            "schema_version": "admanager_daily_dimension_v1",
            "rows": [{"report_date": "2026-05-21", "url_id": "url-zero", "url": "https://example.com/zero", "ad_country_code": "ZZ", "ad_country_name": "Zero", "ad_slot_id": "slot-zero", "ad_slot_name": "Zero", "responses_served": 0, "requests": 0, "impressions": 0, "clicks": 0, "revenue": "0.000000", "ecpm": "0.000000"}],
        },
    )
    assert zero_denominator.status_code == 201
    zero_response = test_client.get(
        "/api/v1/operator/mid-platform/reports/site-daily-dimensions",
        params={"account_id": 1, "report_date": "2026-05-21", "ad_slot_id": "slot-zero"},
    )
    zero_item = zero_response.json()["items"][0]
    assert (zero_item["coverage_rate"], zero_item["click_through_rate"], zero_item["impression_rate"]) == (0.0, 0.0, 0.0)

    with session_factory() as session:
        preserved_hourly = session.scalars(select(AccountHourlyReport)).all()

    assert len(preserved_hourly) == 1
    assert preserved_hourly[0].responses_served == 140


def test_daily_dimension_snapshot_replaces_stale_rows_after_core_batch(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client
    task_id, token = _seed_task(test_client)
    headers = {"Authorization": f"Bearer {token}"}

    with session_factory.begin() as session:
        session.add(
            SiteDailyDimensionReport(
                account_id=1,
                report_date=date(2026, 5, 21),
                url_id="stale-url",
                url="https://example.com/stale",
                ad_country_code="US",
                ad_country_name="United States",
                ad_slot_id="stale-slot",
                ad_slot_name="Stale slot",
                source_kind="authoritative_daily",
                currency="USD",
                responses_served=1,
                requests=1,
                impressions=1,
                clicks=1,
                revenue=Decimal("0.010000"),
                ecpm=Decimal("10.000000"),
                coverage_hours=24,
                expected_hours=24,
                is_complete=True,
            )
        )

    core = test_client.post(
        f"/api/v1/collector/tasks/{task_id}/batches",
        headers=headers,
        json={
            "batch_key": "core-page-1",
            "row_count": 1,
            "payload_hash": "core-hash-1",
            "schema_version": "admanager_site_core_v1",
            "rows": [{"report_date": "2026-05-21", "url_id": "url-1", "url": "https://example.com/a", "responses_served": 10, "requests": 12, "impressions": 8, "clicks": 1, "revenue": "0.100000", "ecpm": "12.500000"}],
        },
    )
    assert core.status_code == 201

    dimensions = test_client.post(
        f"/api/v1/collector/tasks/{task_id}/batches",
        headers=headers,
        json={
            "batch_key": "dimension-page-1",
            "row_count": 1,
            "payload_hash": "dimension-hash-1",
            "schema_version": "admanager_daily_dimension_v1",
            "rows": [{"report_date": "2026-05-21", "url_id": "url-1", "url": "https://example.com/a", "ad_country_code": "CN", "ad_country_name": "China", "ad_slot_id": "slot-1", "ad_slot_name": "Banner", "responses_served": 10, "requests": 12, "impressions": 8, "clicks": 1, "revenue": "0.100000", "ecpm": "12.500000"}],
        },
    )
    assert dimensions.status_code == 201

    with session_factory() as session:
        rows = session.scalars(select(SiteDailyDimensionReport).order_by(SiteDailyDimensionReport.url_id)).all()

    assert [row.url_id for row in rows] == ["url-1"]
def test_authoritative_daily_batch_replaces_core_and_dimension_in_one_request(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client
    task_id, token = _seed_task(test_client)

    rows = [{
        "core_rows": [{
            "report_date": "2026-05-21", "url_id": "site-1", "url": "site-1",
            "responses_served": 50, "requests": 60, "impressions": 40, "clicks": 2,
            "revenue": "1.000000", "ecpm": "25.000000",
        }],
        "dimension_rows": [{
            "report_date": "2026-05-21", "url_id": "site-1", "url": "site-1",
            "ad_country_code": "US", "ad_country_name": "US", "ad_slot_id": "slot-1",
            "ad_slot_name": "Top", "responses_served": 50, "requests": 60,
            "impressions": 40, "clicks": 2, "revenue": "1.000000", "ecpm": "25.000000",
        }],
    }]
    response = test_client.post(
        f"/api/v1/collector/tasks/{task_id}/batches",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "batch_key": "authoritative-snapshot",
            "row_count": 2,
            "payload_hash": _hash_rows(rows),
            "schema_version": "admanager_authoritative_daily_v1",
            "rows": rows,
        },
    )

    assert response.status_code == 201
    repeated_status = test_client.post(
        f"/api/v1/collector/tasks/{task_id}/status",
        headers={"Authorization": f"Bearer {token}"},
        json={"status": "succeeded", "message": "uploaded authoritative snapshot"},
    )
    assert repeated_status.status_code == 200
    with session_factory() as session:
        assert session.scalar(select(AccountDailyReport)).requests == 60
        assert session.scalar(select(SiteDailyReport)).url_id == "site-1"
        assert session.scalar(select(SiteDailyDimensionReport)).ad_slot_id == "slot-1"
        summary = session.scalar(select(AuthoritativeDailyVersionSummary))
        assert summary.task_id == task_id
        assert summary.requests == 60
        assert summary.row_count == 2
        assert summary.payload_hash == _hash_rows(rows)
        assert session.get(_models.CollectorSyncTask, task_id).status == "succeeded"


def test_complete_zero_authoritative_snapshot_clears_existing_daily_reports(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client
    task_id, token = _seed_task(test_client)
    with session_factory() as session:
        session.add(SiteDailyReport(account_id=1, report_date=date(2026, 5, 21), url_id="old", url="old", responses_served=1, requests=1, impressions=1, clicks=0, revenue=0, ecpm=0))
        session.add(AccountDailyReport(account_id=1, report_date=date(2026, 5, 21), responses_served=1, requests=1, impressions=1, clicks=0, revenue=0, ecpm=0))
        session.commit()
    rows = [{"core_rows": [], "dimension_rows": []}]

    response = test_client.post(
        f"/api/v1/collector/tasks/{task_id}/batches",
        headers={"Authorization": f"Bearer {token}"},
        json={"batch_key": "zero", "row_count": 0, "payload_hash": _hash_rows(rows), "schema_version": "admanager_authoritative_daily_v1", "rows": rows},
    )

    assert response.status_code == 201
    with session_factory() as session:
        assert session.scalar(select(SiteDailyReport)) is None
        assert session.scalar(select(AccountDailyReport)) is None


def test_authoritative_snapshot_rejects_false_row_count_and_hash(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, _ = client
    task_id, token = _seed_task(test_client)
    rows = [{"core_rows": [], "dimension_rows": []}]

    response = test_client.post(
        f"/api/v1/collector/tasks/{task_id}/batches",
        headers={"Authorization": f"Bearer {token}"},
        json={"batch_key": "invalid", "row_count": 1, "payload_hash": "false", "schema_version": "admanager_authoritative_daily_v1", "rows": rows},
    )

    assert response.status_code == 422


def test_new_authoritative_version_clears_previous_full_payload(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client
    first_task_id, token = _seed_task(test_client)
    first_rows = [{"core_rows": [], "dimension_rows": []}]
    assert test_client.post(
        f"/api/v1/collector/tasks/{first_task_id}/batches",
        headers={"Authorization": f"Bearer {token}"},
        json={"batch_key": "first", "row_count": 0, "payload_hash": _hash_rows(first_rows), "schema_version": "admanager_authoritative_daily_v1", "rows": first_rows},
    ).status_code == 201
    with session_factory() as session:
        second = _models.CollectorSyncTask(
            account_id=1, collector_instance_id=1, task_type="report_fetch",
            report_date=date(2026, 5, 21), status="pending", authoritative_slot=8,
            external_request_id="second-authoritative-version",
        )
        session.add(second)
        session.commit()
        second_task_id = second.id
    assert test_client.post(
        f"/api/v1/collector/tasks/{second_task_id}/batches",
        headers={"Authorization": f"Bearer {token}"},
        json={"batch_key": "second", "row_count": 0, "payload_hash": _hash_rows(first_rows), "schema_version": "admanager_authoritative_daily_v1", "rows": first_rows},
    ).status_code == 201

    with session_factory() as session:
        batches = session.scalars(select(CollectorIngestionBatch).order_by(CollectorIngestionBatch.id)).all()
        assert batches[0].payload_json is None
        assert batches[1].payload_json is not None


def test_earlier_authoritative_slot_cannot_overwrite_later_published_slot(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client
    early_task_id, token = _seed_task(test_client)
    with session_factory() as session:
        session.get(_models.CollectorSyncTask, early_task_id).authoritative_slot = 5
        later_task = _models.CollectorSyncTask(
            account_id=1, collector_instance_id=1, task_type="report_fetch",
            report_date=date(2026, 5, 21), status="succeeded", authoritative_slot=7,
            external_request_id="later-slot-7",
        )
        session.add(later_task)
        session.flush()
        session.add(AuthoritativeDailyVersionSummary(
            task_id=later_task.id, account_id=1, report_date=date(2026, 5, 21), slot=7,
            responses_served=70, requests=70, impressions=70, clicks=7,
            revenue=Decimal("7"), row_count=1, payload_hash="later",
        ))
        session.commit()

    late_rows = [{"core_rows": [], "dimension_rows": []}]
    response = test_client.post(
        f"/api/v1/collector/tasks/{early_task_id}/batches",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "batch_key": "late-slot-5", "row_count": 0, "payload_hash": _hash_rows(late_rows),
            "schema_version": "admanager_authoritative_daily_v1",
            "rows": late_rows,
        },
    )

    assert response.status_code == 409


def test_legacy_null_slot_cannot_overwrite_later_published_slot(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client
    legacy_task_id, token = _seed_task(test_client)
    with session_factory() as session:
        later = _models.CollectorSyncTask(
            account_id=1, collector_instance_id=1, task_type="report_fetch",
            report_date=date(2026, 5, 21), status="succeeded", authoritative_slot=7,
            external_request_id="published-slot-7-before-legacy",
        )
        session.add(later)
        session.flush()
        session.add(AuthoritativeDailyVersionSummary(
            task_id=later.id, account_id=1, report_date=date(2026, 5, 21), slot=7,
            responses_served=70, requests=70, impressions=70, clicks=7,
            revenue=Decimal("7"), row_count=1, payload_hash="later",
        ))
        session.commit()
    rows = [{"core_rows": [], "dimension_rows": []}]

    response = test_client.post(
        f"/api/v1/collector/tasks/{legacy_task_id}/batches",
        headers={"Authorization": f"Bearer {token}"},
        json={"batch_key": "legacy-null", "row_count": 0, "payload_hash": _hash_rows(rows), "schema_version": "admanager_authoritative_daily_v1", "rows": rows},
    )

    assert response.status_code == 409


def test_beijing_date_range_spans_previous_and_current_utc_dates() -> None:
    start_utc, end_utc = _beijing_date_range_utc(date(2026, 8, 5), date(2026, 8, 5))

    assert start_utc == datetime(2026, 8, 4, 16, 0)
    assert end_utc == datetime(2026, 8, 5, 16, 0)
