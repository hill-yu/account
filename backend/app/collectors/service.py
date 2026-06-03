from __future__ import annotations

from datetime import date, datetime, timezone
from secrets import token_urlsafe

from fastapi import HTTPException, status
from sqlalchemy import case, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.collectors import schemas
from app.models.account import Account
from app.models.account_daily_report import AccountDailyReport
from app.models.collector_instance import CollectorInstance
from app.models.collector_sync_log import CollectorSyncLog
from app.models.collector_sync_task import CollectorSyncTask
from app.models.oauth_app_config import OAuthAppConfig
from app.models.proxy_binding import ProxyBinding
from app.models.site_daily_report import SiteDailyReport


TERMINAL_TASK_STATUSES = {"succeeded", "failed", "cancelled"}
ALLOWED_STATUS_TRANSITIONS = {
    "pending": {"in_progress", "blocked", "cancelled"},
    "in_progress": {"succeeded", "failed", "cancelled", "blocked"},
    "blocked": {"pending", "cancelled"},
    "succeeded": set(),
    "failed": set(),
    "cancelled": set(),
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def allowed_source_statuses(target_status: str) -> set[str]:
    return {
        current_status
        for current_status, allowed_targets in ALLOWED_STATUS_TRANSITIONS.items()
        if target_status in allowed_targets
    }


def commit_or_raise_conflict(db: Session, detail: str) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail) from exc


def list_accounts(db: Session) -> list[Account]:
    return list(db.scalars(select(Account).order_by(Account.id)))


def create_account(db: Session, payload: schemas.AccountCreate) -> Account:
    account = Account(
        name=payload.name,
        status=payload.status,
        external_account_id=payload.external_account_id,
    )
    db.add(account)
    commit_or_raise_conflict(db, "Account already exists")
    db.refresh(account)
    return account


def list_instances(db: Session) -> list[CollectorInstance]:
    return list(db.scalars(select(CollectorInstance).order_by(CollectorInstance.id)))


def create_instance(db: Session, payload: schemas.InstanceCreate) -> CollectorInstance:
    account = db.get(Account, payload.account_id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    instance = CollectorInstance(
        account_id=payload.account_id,
        name=payload.name,
        instance_token=payload.instance_token or token_urlsafe(24),
        status=payload.status,
        expected_egress_ip=payload.expected_egress_ip,
    )
    db.add(instance)
    commit_or_raise_conflict(db, "Collector instance already exists")
    db.refresh(instance)
    return instance


def list_proxies(db: Session) -> list[ProxyBinding]:
    return list(db.scalars(select(ProxyBinding).order_by(ProxyBinding.id)))


def create_proxy_binding(db: Session, payload: schemas.ProxyBindingCreate) -> ProxyBinding:
    account = db.get(Account, payload.account_id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    instance = db.get(CollectorInstance, payload.collector_instance_id)
    if instance is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collector instance not found")
    if instance.account_id != payload.account_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Collector instance account does not match proxy binding account",
        )

    proxy_binding = ProxyBinding(
        account_id=payload.account_id,
        collector_instance_id=payload.collector_instance_id,
        provider_name=payload.provider_name,
        protocol=payload.protocol,
        host=payload.host,
        port=payload.port,
        username=payload.username,
        password=payload.password,
        expected_egress_ip=payload.expected_egress_ip,
        status=payload.status,
    )
    db.add(proxy_binding)
    commit_or_raise_conflict(db, "Proxy binding already exists for this account or instance")
    db.refresh(proxy_binding)
    return proxy_binding


def list_tasks(db: Session) -> list[CollectorSyncTask]:
    return list(db.scalars(select(CollectorSyncTask).order_by(CollectorSyncTask.id)))


def create_task(db: Session, payload: schemas.SyncTaskCreate) -> CollectorSyncTask:
    account = db.get(Account, payload.account_id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    instance = db.get(CollectorInstance, payload.collector_instance_id)
    if instance is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collector instance not found")
    if instance.account_id != payload.account_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Collector instance account does not match task account",
        )

    task = CollectorSyncTask(
        account_id=payload.account_id,
        collector_instance_id=payload.collector_instance_id,
        task_type=payload.task_type,
        report_date=payload.report_date,
        status=payload.status,
        external_request_id=payload.external_request_id,
    )
    db.add(task)
    commit_or_raise_conflict(db, "Sync task already exists")
    db.refresh(task)
    return task


def list_account_daily_reports(
    db: Session,
    *,
    account_id: int | None = None,
    report_date: date | None = None,
) -> list[AccountDailyReport]:
    query = select(AccountDailyReport).order_by(AccountDailyReport.report_date.desc(), AccountDailyReport.account_id.asc())
    if account_id is not None:
        query = query.where(AccountDailyReport.account_id == account_id)
    if report_date is not None:
        query = query.where(AccountDailyReport.report_date == report_date)
    return list(db.scalars(query))


def list_site_daily_reports(
    db: Session,
    *,
    account_id: int | None = None,
    report_date: date | None = None,
) -> list[SiteDailyReport]:
    query = select(SiteDailyReport).order_by(
        SiteDailyReport.report_date.desc(),
        SiteDailyReport.account_id.asc(),
        SiteDailyReport.url.asc(),
    )
    if account_id is not None:
        query = query.where(SiteDailyReport.account_id == account_id)
    if report_date is not None:
        query = query.where(SiteDailyReport.report_date == report_date)
    return list(db.scalars(query))


def build_runtime_config(
    db: Session,
    instance: CollectorInstance,
    *,
    control_plane_base_url: str,
    egress_check_url: str = "https://api.ipify.org",
    request_timeout_seconds: int = 30,
) -> schemas.CollectorRuntimeConfigResponse:
    proxy_binding = db.scalar(
        select(ProxyBinding).where(
            ProxyBinding.collector_instance_id == instance.id,
            ProxyBinding.account_id == instance.account_id,
        )
    )
    if proxy_binding is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Collector instance has no proxy binding")

    oauth_app = db.scalar(select(OAuthAppConfig).where(OAuthAppConfig.account_id == instance.account_id))
    google_runtime = schemas.CollectorGoogleRuntimeCredentials(fetch_mode="stub")
    if oauth_app is not None:
        if oauth_app.authorization_status != "authorized" or not oauth_app.refresh_token_present:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="OAuth app is not authorized for runtime fetch",
            )
        account = db.get(Account, instance.account_id)
        if account is None or account.external_account_id is None or account.external_account_id == "":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Account external_account_id must be set to the Ad Manager network code",
            )
        google_runtime = schemas.CollectorGoogleRuntimeCredentials(
            fetch_mode="admanager_soap",
            admanager_network_code=account.external_account_id,
            google_oauth_client_id=oauth_app.client_id,
            google_oauth_client_secret=oauth_app.client_secret,
            google_oauth_refresh_token=oauth_app.refresh_token,
        )

    return schemas.CollectorRuntimeConfigResponse(
        control_plane_base_url=control_plane_base_url.rstrip("/"),
        instance_id=instance.id,
        account_id=instance.account_id,
        expected_egress_ip=proxy_binding.expected_egress_ip,
        proxy_protocol=proxy_binding.protocol,
        proxy_host=proxy_binding.host,
        proxy_port=proxy_binding.port,
        proxy_username=proxy_binding.username,
        proxy_password=proxy_binding.password,
        egress_check_url=egress_check_url,
        request_timeout_seconds=request_timeout_seconds,
        google=google_runtime,
    )


def record_heartbeat(
    db: Session,
    instance: CollectorInstance,
    payload: schemas.HeartbeatRequest,
) -> tuple[CollectorInstance, str | None]:
    instance.last_heartbeat_at = utcnow()
    if payload.status is not None:
        instance.status = payload.status
    db.add(instance)
    db.commit()
    db.refresh(instance)
    return instance, payload.observed_egress_ip


def claim_next_task(db: Session, instance: CollectorInstance) -> CollectorSyncTask | None:
    claimed_at = utcnow()
    next_task_id = (
        select(CollectorSyncTask.id)
        .where(
            CollectorSyncTask.collector_instance_id == instance.id,
            CollectorSyncTask.status == "pending",
        )
        .order_by(CollectorSyncTask.created_at, CollectorSyncTask.id)
        .limit(1)
        .scalar_subquery()
    )
    claimed = db.execute(
        update(CollectorSyncTask)
        .where(
            CollectorSyncTask.id == next_task_id,
            CollectorSyncTask.status == "pending",
        )
        .values(status="in_progress", started_at=claimed_at)
        .returning(CollectorSyncTask)
    ).scalar_one_or_none()
    if claimed is None:
        db.rollback()
        return None
    db.commit()
    return claimed


def update_task_status(
    db: Session,
    instance: CollectorInstance,
    task_id: int,
    payload: schemas.TaskStatusUpdate,
) -> CollectorSyncTask:
    source_statuses = allowed_source_statuses(payload.status)
    if not source_statuses:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Invalid task status transition")

    finished_at = utcnow() if payload.status in TERMINAL_TASK_STATUSES else None
    updated_task = db.execute(
        update(CollectorSyncTask)
        .where(
            CollectorSyncTask.id == task_id,
            CollectorSyncTask.collector_instance_id == instance.id,
            CollectorSyncTask.status.in_(source_statuses),
        )
        .values(
            status=payload.status,
            started_at=case(
                (CollectorSyncTask.started_at.is_(None), utcnow()),
                else_=CollectorSyncTask.started_at,
            ),
            finished_at=finished_at,
            updated_at=utcnow(),
        )
        .returning(CollectorSyncTask)
    ).scalar_one_or_none()

    if updated_task is None:
        task = db.scalar(
            select(CollectorSyncTask).where(
                CollectorSyncTask.id == task_id,
                CollectorSyncTask.collector_instance_id == instance.id,
            )
        )
        if task is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Invalid task status transition")
    if payload.message:
        db.add(
            CollectorSyncLog(
                task_id=updated_task.id,
                account_id=updated_task.account_id,
                collector_instance_id=instance.id,
                level="error" if payload.status == "failed" else "info",
                message=payload.message,
            )
        )
    commit_or_raise_conflict(db, "Unable to update task status")
    db.refresh(updated_task)
    return updated_task
