from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.vps_database import VpsBase, build_engine
from app.vps_config import VpsApiSettings


def test_vps_settings_defaults_are_repo_local_and_deterministic() -> None:
    expected_base_dir = Path(__file__).resolve().parents[1]
    settings = VpsApiSettings()

    assert settings.database_url == f"sqlite:///{(expected_base_dir / 'vps_api.db').as_posix()}"
    assert Path(VpsApiSettings.model_config["env_file"]) == expected_base_dir / ".env"


def test_get_engine_uses_configured_database_url(monkeypatch, tmp_path) -> None:
    from app import vps_database

    database_path = tmp_path / "configured.db"
    monkeypatch.setenv("ADX_VPS_DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    monkeypatch.setenv("ADX_VPS_SQL_ECHO", "false")
    vps_database.get_vps_settings.cache_clear()
    vps_database.get_engine.cache_clear()
    vps_database.get_session_factory.cache_clear()

    try:
        engine = vps_database.get_engine()
        assert engine.url.render_as_string(hide_password=False) == f"sqlite:///{database_path.as_posix()}"
    finally:
        vps_database.get_session_factory.cache_clear()
        vps_database.get_engine.cache_clear()
        vps_database.get_vps_settings.cache_clear()


def test_vps_schema_creates_expected_tables(tmp_path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'vps.db').as_posix()}"
    engine = build_engine(database_url, sql_echo=False)

    from app import vps_models  # noqa: F401

    VpsBase.metadata.create_all(bind=engine)

    inspector = inspect(engine)
    assert set(inspector.get_table_names()) == {
        "adx_account_proxies",
        "adx_accounts",
        "adx_fetch_runs",
        "adx_site_daily_reports",
    }


def test_vps_schema_enforces_unique_site_report_per_account_date_and_site(tmp_path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'vps.db').as_posix()}"
    engine = build_engine(database_url, sql_echo=False)

    from app.vps_database import build_session_factory
    from app.vps_models import AdxAccount, AdxFetchRun, AdxSiteDailyReport

    VpsBase.metadata.create_all(bind=engine)
    session_factory = build_session_factory(database_url, sql_echo=False)

    with session_factory() as db:
        account = AdxAccount(
            account_key="account-1",
            account_name="Account 1",
            network_code="23347208010",
            client_id="client-id",
            client_secret="client-secret",
            refresh_token="refresh-token",
            status="active",
        )
        db.add(account)
        db.flush()

        run = AdxFetchRun(
            account_id=account.id,
            report_date=date(2026, 5, 14),
            trigger_source="test",
            request_id="req-001",
            status="success",
            row_count=1,
        )
        db.add(run)
        db.flush()

        first_row = AdxSiteDailyReport(
            account_id=account.id,
            report_date=date(2026, 5, 14),
            site_name="example.com",
            responses_served=10,
            impressions=9,
            clicks=1,
            revenue="1.000000",
            ecpm="100.000000",
            fetch_run_id=run.id,
        )
        duplicate_row = AdxSiteDailyReport(
            account_id=account.id,
            report_date=date(2026, 5, 14),
            site_name="example.com",
            responses_served=11,
            impressions=10,
            clicks=2,
            revenue="2.000000",
            ecpm="200.000000",
            fetch_run_id=run.id,
        )

        db.add(first_row)
        db.flush()
        db.add(duplicate_row)

        with pytest.raises(IntegrityError):
            db.flush()
