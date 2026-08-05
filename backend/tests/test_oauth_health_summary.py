from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.collectors import oauth_service
from app.database import Base, get_db
from app.main import create_app
from app.models import Account, AccountHourlyReport, CollectorInstance, CollectorSyncTask, OAuthAppConfig, OAuthCredential


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'oauth-health.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    app = create_app()

    def override_get_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    now = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(oauth_service, "utcnow", lambda: now)
    monkeypatch.setattr(
        oauth_service.requests,
        "get",
        lambda *args, **kwargs: pytest.fail("health summary must not call Google"),
        raising=False,
    )
    monkeypatch.setattr(
        oauth_service.requests,
        "post",
        lambda *args, **kwargs: pytest.fail("health summary must not call Google"),
    )

    with factory() as db:
        healthy = _seed_app(
            db,
            name="healthy",
            runtime_status="healthy",
            active_version=2,
            credential_version=1,
        )
        degraded = _seed_app(
            db,
            name="degraded",
            runtime_status="degraded",
            failure_class="oauth_provider_unavailable",
            failure_count=2,
        )
        revoked = _seed_app(
            db,
            name="revoked",
            runtime_status="revoked",
            failure_class="oauth_refresh_revoked",
            failure_count=3,
            revoked_at=now - timedelta(days=1),
        )
        db.add(
            AccountHourlyReport(
                account_id=healthy.account_id,
                report_date=date(2026, 7, 31),
                hour=5,
                report_time_utc=now - timedelta(hours=7),
                source_timezone="UTC",
            )
        )
        healthy_instance = db.query(CollectorInstance).filter_by(account_id=healthy.account_id).one()
        revoked_instance = db.query(CollectorInstance).filter_by(account_id=revoked.account_id).one()
        db.add_all(
            [
                CollectorSyncTask(
                    account_id=healthy.account_id,
                    collector_instance_id=healthy_instance.id,
                    task_type="report_fetch",
                    report_date=date(2026, 7, 29),
                    status="succeeded",
                    external_request_id="authoritative-healthy-2026-07-29",
                ),
                CollectorSyncTask(
                    account_id=revoked.account_id,
                    collector_instance_id=revoked_instance.id,
                    task_type="report_fetch_hourly",
                    report_date=date(2026, 7, 31),
                    status="pending",
                    created_at=now,
                    external_request_id="revoked-task-violation",
                ),
            ]
        )
        db.commit()

    with TestClient(app) as test_client:
        test_client.headers.update({"X-ADX-Operator-Token": "test-operator-token"})
        yield test_client

    app.dependency_overrides.clear()
    engine.dispose()


def _seed_app(
    db: Session,
    *,
    name: str,
    runtime_status: str,
    active_version: int = 1,
    credential_version: int = 1,
    failure_class: str | None = None,
    failure_count: int = 0,
    revoked_at: datetime | None = None,
) -> OAuthAppConfig:
    account = Account(name=f"{name}.com", status="active", timezone="UTC", external_account_id=f"network-{name}")
    db.add(account)
    db.flush()
    instance = CollectorInstance(
        account_id=account.id,
        name=name,
        instance_token=f"instance-{name}",
        status="active",
        report_account_key=name,
    )
    oauth_app = OAuthAppConfig(
        account_id=account.id,
        client_id=f"client-{name}",
        client_secret="",
        redirect_uri=f"https://{name}.com/oauth/google/callback",
        scopes="https://www.googleapis.com/auth/admanager",
        authorization_status="authorized",
        flow_status="completed",
        runtime_status=runtime_status,
        active_credential_version=active_version,
        failure_class=failure_class,
        failure_count=failure_count,
        revoked_at=revoked_at,
    )
    db.add_all([instance, oauth_app])
    db.flush()
    db.add(
        OAuthCredential(
            oauth_app_id=oauth_app.id,
            version=credential_version,
            status="active",
            client_secret_ciphertext=f"cipher-client-{name}",
            refresh_token_ciphertext=f"cipher-refresh-{name}",
            token_fingerprint=f"fingerprint-{name}",
        )
    )
    db.flush()
    return oauth_app


def test_oauth_health_summary_returns_local_aggregates_without_secrets(client: TestClient) -> None:
    response = client.get("/api/v1/operator/oauth/health-summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["oauth_runtime_status_accounts"] == {"degraded": 1, "healthy": 1, "revoked": 1}
    assert payload["oauth_refresh_failure_total"] == {
        "oauth_provider_unavailable": 2,
        "oauth_refresh_revoked": 3,
    }
    assert payload["oauth_credential_version_mismatch_total"] == 1
    assert payload["revoked_account_task_created_total"] == 1
    healthy_lag = next(item for item in payload["account_lags"] if item["account_name"] == "healthy.com")
    assert healthy_lag["hourly_watermark_lag_hours"] == 7.0
    # 权威日报滞后从业务日结束后五小时开始计算，不把稳定等待窗口计为滞后。
    assert healthy_lag["authoritative_daily_lag_hours"] == 7.0
    serialized = response.text
    assert "cipher-client" not in serialized
    assert "cipher-refresh" not in serialized
    assert "instance-healthy" not in serialized
