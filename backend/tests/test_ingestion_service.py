from __future__ import annotations

from collections.abc import Generator
import json
from datetime import datetime
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


def test_hourly_dimension_batch_projects_hourly_facts_and_rebuilds_daily_rollups(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client
    task_id, token = _seed_task(test_client)
    headers = {"Authorization": f"Bearer {token}"}

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

    assert len(site_daily_rows) == 2
    assert len(account_daily_rows) == 1
    assert account_daily_rows[0].responses_served == 140
    assert account_daily_rows[0].requests == 190
    assert account_daily_rows[0].impressions == 100
    assert account_daily_rows[0].clicks == 5
    assert account_daily_rows[0].revenue == 2

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
    }

    account_daily = test_client.get(
        "/api/v1/operator/reports/account-daily",
        params={"account_id": 1, "report_date": "2026-05-21"},
    )
    assert account_daily.status_code == 200
    assert account_daily.json()["coverage"]["hours_present"] == [9]
    assert account_daily.json()["coverage"]["is_complete_day"] is False
