from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.collectors import schemas
from app.models.account_daily_report import AccountDailyReport
from app.models.collector_ingestion_batch import CollectorIngestionBatch
from app.models.collector_instance import CollectorInstance
from app.models.collector_sync_task import CollectorSyncTask
from app.models.site_daily_report import SiteDailyReport


def ingest_batch(
    db: Session,
    instance: CollectorInstance,
    task_id: int,
    payload: schemas.BatchIngestionRequest,
) -> tuple[CollectorIngestionBatch, bool]:
    task = db.scalar(
        select(CollectorSyncTask).where(
            CollectorSyncTask.id == task_id,
            CollectorSyncTask.collector_instance_id == instance.id,
        )
    )
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    payload_json = json.dumps(payload.rows, separators=(",", ":"), sort_keys=True) if payload.rows is not None else None
    is_first_batch_for_task = db.scalar(
        select(CollectorIngestionBatch.id).where(CollectorIngestionBatch.task_id == task_id).limit(1)
    ) is None

    existing = db.scalar(
        select(CollectorIngestionBatch).where(
            CollectorIngestionBatch.task_id == task_id,
            CollectorIngestionBatch.batch_key == payload.batch_key,
        )
    )
    if existing is not None:
        if (
            existing.row_count != payload.row_count
            or existing.payload_hash != payload.payload_hash
            or existing.schema_version != payload.schema_version
            or existing.payload_json != payload_json
        ):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Batch key already used with different payload")
        return existing, True

    batch = CollectorIngestionBatch(
        task_id=task.id,
        account_id=task.account_id,
        batch_key=payload.batch_key,
        row_count=payload.row_count,
        payload_hash=payload.payload_hash,
        schema_version=payload.schema_version,
        payload_json=payload_json,
    )
    db.add(batch)
    try:
        _project_payload_if_supported(
            db,
            task=task,
            schema_version=payload.schema_version,
            rows=payload.rows,
            reset_existing=is_first_batch_for_task,
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = db.scalar(
            select(CollectorIngestionBatch).where(
                CollectorIngestionBatch.task_id == task_id,
                CollectorIngestionBatch.batch_key == payload.batch_key,
            )
        )
        if existing is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Batch key already used") from exc
        if (
            existing.row_count != payload.row_count
            or existing.payload_hash != payload.payload_hash
            or existing.schema_version != payload.schema_version
            or existing.payload_json != payload_json
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Batch key already used with different payload",
            ) from exc
        return existing, True

    db.refresh(batch)
    return batch, False


def _project_payload_if_supported(
    db: Session,
    *,
    task: CollectorSyncTask,
    schema_version: str | None,
    rows: list[dict[str, Any]] | None,
    reset_existing: bool,
) -> None:
    if not rows or schema_version != "admanager_site_core_v1":
        return
    normalized_rows = [_normalize_admanager_site_row(row, task.report_date) for row in rows]
    if reset_existing:
        db.execute(
            delete(SiteDailyReport).where(
                SiteDailyReport.account_id == task.account_id,
                SiteDailyReport.report_date == task.report_date,
            )
        )
        db.execute(
            delete(AccountDailyReport).where(
                AccountDailyReport.account_id == task.account_id,
                AccountDailyReport.report_date == task.report_date,
            )
        )

    for row in normalized_rows:
        existing = db.scalar(
            select(SiteDailyReport).where(
                SiteDailyReport.account_id == task.account_id,
                SiteDailyReport.report_date == task.report_date,
                SiteDailyReport.url_id == row["url_id"],
            )
        )
        if existing is None:
            existing = SiteDailyReport(account_id=task.account_id, report_date=task.report_date, url_id=row["url_id"])
            db.add(existing)
        existing.url = row["url"]
        existing.responses_served = row["responses_served"]
        existing.impressions = row["impressions"]
        existing.clicks = row["clicks"]
        existing.revenue = row["revenue"]
        existing.ecpm = row["ecpm"]

    db.flush()
    _rebuild_account_daily_report(db, account_id=task.account_id, report_date=task.report_date)


def _normalize_admanager_site_row(row: dict[str, Any], report_date: date) -> dict[str, Any]:
    row_report_date = row.get("report_date")
    if row_report_date is None or date.fromisoformat(str(row_report_date)) != report_date:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Batch row report_date mismatch")
    try:
        return {
            "url_id": str(row["url_id"]),
            "url": str(row["url"]),
            "responses_served": int(row["responses_served"]),
            "impressions": int(row["impressions"]),
            "clicks": int(row["clicks"]),
            "revenue": Decimal(str(row["revenue"])),
            "ecpm": Decimal(str(row["ecpm"])),
        }
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Batch rows do not match admanager_site_core_v1 schema") from exc


def _rebuild_account_daily_report(db: Session, *, account_id: int, report_date: date) -> None:
    rows = list(
        db.scalars(
            select(SiteDailyReport).where(
                SiteDailyReport.account_id == account_id,
                SiteDailyReport.report_date == report_date,
            )
        )
    )
    existing = db.scalar(
        select(AccountDailyReport).where(
            AccountDailyReport.account_id == account_id,
            AccountDailyReport.report_date == report_date,
        )
    )
    if not rows:
        if existing is not None:
            db.delete(existing)
        return

    responses_served = sum(row.responses_served for row in rows)
    impressions = sum(row.impressions for row in rows)
    clicks = sum(row.clicks for row in rows)
    revenue = sum((row.revenue for row in rows), start=Decimal("0"))
    ecpm = Decimal("0")
    if impressions > 0:
        ecpm = (revenue * Decimal("1000")) / Decimal(impressions)
        ecpm = ecpm.quantize(Decimal("0.000001"))

    if existing is None:
        existing = AccountDailyReport(account_id=account_id, report_date=report_date)
        db.add(existing)

    existing.responses_served = responses_served
    existing.impressions = impressions
    existing.clicks = clicks
    existing.revenue = revenue.quantize(Decimal("0.000001"))
    existing.ecpm = ecpm
