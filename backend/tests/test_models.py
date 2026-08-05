from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.database import Base, get_db, get_engine, get_session_factory
from app.main import create_app
from app import models as _models  # noqa: F401


EXPECTED_TABLES = {
    "accounts",
    "account_daily_reports",
    "account_daily_dimension_reports",
    "account_hourly_reports",
    "site_daily_reports",
    "site_daily_dimension_reports",
    "site_hourly_reports",
    "oauth_app_configs",
    "collector_instances",
    "proxy_bindings",
    "collector_sync_tasks",
    "collector_sync_logs",
    "collector_ingestion_batches",
    "fetch_schedules",
    "account_report_day_statuses",
    "oauth_credentials",
    "collector_account_policies",
    "oauth_events",
    "authoritative_daily_version_summaries",
}


def test_metadata_exposes_phase1_tables() -> None:
    assert EXPECTED_TABLES == set(Base.metadata.tables)


def test_configured_sqlite_database_path_is_absolute() -> None:
    database_url = get_engine().url.render_as_string(hide_password=False)

    assert database_url.startswith("sqlite:///")
    sqlite_path = Path(database_url.removeprefix("sqlite:///"))
    assert sqlite_path.is_absolute()


def test_session_factory_returns_session_and_dependency_closes_it() -> None:
    session_factory = get_session_factory()
    session = session_factory()

    assert isinstance(session, Session)
    assert session.is_active

    dependency = get_db()
    yielded = next(dependency)
    assert isinstance(yielded, Session)

    yielded.close()
    try:
        next(dependency)
    except StopIteration:
        pass

    assert yielded.is_active


def test_create_all_creates_tables() -> None:
    engine = create_engine("sqlite:///:memory:")

    Base.metadata.create_all(engine)

    inspector = inspect(engine)
    assert EXPECTED_TABLES.issubset(set(inspector.get_table_names()))


def test_daily_dimension_report_tables_have_full_dimension_unique_keys() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)

    account_constraints = inspector.get_unique_constraints("account_daily_dimension_reports")
    site_constraints = inspector.get_unique_constraints("site_daily_dimension_reports")

    assert any(
        constraint["column_names"] == [
            "account_id", "report_date", "ad_country_code", "ad_slot_id", "source_kind"
        ]
        for constraint in account_constraints
    )
    assert any(
        constraint["column_names"] == [
            "account_id", "report_date", "url_id", "ad_country_code", "ad_slot_id", "source_kind"
        ]
        for constraint in site_constraints
    )
    assert {index["name"] for index in inspector.get_indexes("account_daily_dimension_reports")} == {
        "ix_account_daily_dimension_reports_lookup"
    }
    assert {index["name"] for index in inspector.get_indexes("site_daily_dimension_reports")} == {
        "ix_site_daily_dimension_reports_lookup"
    }


def test_healthcheck_returns_ok() -> None:
    client = TestClient(create_app())
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
