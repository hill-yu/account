from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.collectors import schemas, service
from app.models.account import Account
from app.models.account_daily_report import AccountDailyReport
from app.models.account_hourly_report import AccountHourlyReport
from app.models.collector_ingestion_batch import CollectorIngestionBatch
from app.models.collector_instance import CollectorInstance
from app.models.collector_sync_task import CollectorSyncTask
from app.models.site_daily_report import SiteDailyReport
from app.models.site_hourly_report import SiteHourlyReport


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
    service._assert_task_credential_is_current(
        db,
        instance=instance,
        task=task,
        supplied_version=payload.credential_version,
    )

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
    if not rows:
        return
    if schema_version == "admanager_site_core_v1":
        normalized_rows = [_normalize_admanager_site_row(row, task.report_date) for row in rows]
        if reset_existing:
            _reset_daily_projection(db, account_id=task.account_id, report_date=task.report_date)

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
            existing.requests = row["requests"]
            existing.impressions = row["impressions"]
            existing.clicks = row["clicks"]
            existing.revenue = row["revenue"]
            existing.ecpm = row["ecpm"]

        db.flush()
        _rebuild_account_daily_report(db, account_id=task.account_id, report_date=task.report_date)
        return

    if schema_version == "admanager_hourly_dimension_v1":
        account = db.get(Account, task.account_id)
        if account is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

        normalized_rows = [
            _normalize_admanager_hourly_site_row(row, report_date=task.report_date, account=account)
            for row in rows
        ]
        if reset_existing:
            _reset_daily_projection(db, account_id=task.account_id, report_date=task.report_date)
            _reset_hourly_projection(db, account_id=task.account_id, report_date=task.report_date)

        for row in normalized_rows:
            existing = db.scalar(
                select(SiteHourlyReport).where(
                    SiteHourlyReport.account_id == task.account_id,
                    SiteHourlyReport.url_id == row["url_id"],
                    SiteHourlyReport.report_time_utc == row["report_time_utc"],
                    SiteHourlyReport.ad_country_code == row["ad_country_code"],
                    SiteHourlyReport.ad_slot_id == row["ad_slot_id"],
                )
            )
            if existing is None:
                existing = SiteHourlyReport(
                    account_id=task.account_id,
                    url_id=row["url_id"],
                    report_time_utc=row["report_time_utc"],
                    ad_country_code=row["ad_country_code"],
                    ad_slot_id=row["ad_slot_id"],
                    report_date=task.report_date,
                    hour=row["hour"],
                )
                db.add(existing)
            existing.report_date = row["report_date"]
            existing.hour = row["hour"]
            existing.source_timezone = row["source_timezone"]
            existing.currency = row["currency"]
            existing.url = row["url"]
            existing.ad_country_name = row["ad_country_name"]
            existing.ad_slot_name = row["ad_slot_name"]
            existing.responses_served = row["responses_served"]
            existing.requests = row["requests"]
            existing.impressions = row["impressions"]
            existing.clicks = row["clicks"]
            existing.revenue = row["revenue"]
            existing.ecpm = row["ecpm"]

        db.flush()
        _rebuild_account_hourly_reports(db, account_id=task.account_id, report_date=task.report_date)
        _rebuild_site_daily_reports_from_hourly(db, account_id=task.account_id, report_date=task.report_date)
        _rebuild_account_daily_report(db, account_id=task.account_id, report_date=task.report_date)
        return


def _normalize_admanager_site_row(row: dict[str, Any], report_date: date) -> dict[str, Any]:
    row_report_date = row.get("report_date")
    if row_report_date is None or date.fromisoformat(str(row_report_date)) != report_date:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Batch row report_date mismatch")
    try:
        return {
            "url_id": str(row["url_id"]),
            "url": str(row["url"]),
            "responses_served": int(row["responses_served"]),
            "requests": int(row.get("requests", 0)),
            "impressions": int(row["impressions"]),
            "clicks": int(row["clicks"]),
            "revenue": Decimal(str(row["revenue"])),
            "ecpm": Decimal(str(row["ecpm"])),
        }
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Batch rows do not match admanager_site_core_v1 schema") from exc


def _normalize_admanager_hourly_site_row(
    row: dict[str, Any],
    *,
    report_date: date,
    account: Account,
) -> dict[str, Any]:
    row_report_date = row.get("report_date")
    if row_report_date is None or date.fromisoformat(str(row_report_date)) != report_date:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Batch row report_date mismatch")

    try:
        hour = int(row["hour"])
        source_timezone = str(row.get("source_timezone") or account.timezone)
        report_time_utc_raw = row.get("report_time_utc")
        report_time_utc = (
            service.build_report_time_utc(report_date=report_date, hour=hour, source_timezone=source_timezone)
            if report_time_utc_raw is None
            else _parse_report_time_utc(report_time_utc_raw)
        )
        impressions = int(row["impressions"])
        revenue = Decimal(str(row["revenue"])).quantize(Decimal("0.000001"))
        ecpm_raw = row.get("ecpm")
        ecpm = (
            Decimal(str(ecpm_raw)).quantize(Decimal("0.000001"))
            if ecpm_raw is not None
            else _calculate_ecpm(revenue=revenue, impressions=impressions)
        )
        return {
            "report_date": report_date,
            "hour": hour,
            "report_time_utc": report_time_utc,
            "source_timezone": source_timezone,
            "currency": str(row.get("currency") or account.currency),
            "url_id": str(row["url_id"]),
            "url": str(row["url"]),
            "ad_country_code": str(row.get("ad_country_code") or "ALL"),
            "ad_country_name": str(row.get("ad_country_name") or "All"),
            "ad_slot_id": str(row.get("ad_slot_id") or "ALL"),
            "ad_slot_name": str(row.get("ad_slot_name") or "All"),
            "responses_served": int(row["responses_served"]),
            "requests": int(row.get("requests", 0)),
            "impressions": impressions,
            "clicks": int(row["clicks"]),
            "revenue": revenue,
            "ecpm": ecpm,
        }
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Batch rows do not match admanager_hourly_dimension_v1 schema",
        ) from exc


def _reset_daily_projection(db: Session, *, account_id: int, report_date: date) -> None:
    db.execute(
        delete(SiteDailyReport).where(
            SiteDailyReport.account_id == account_id,
            SiteDailyReport.report_date == report_date,
        )
    )
    db.execute(
        delete(AccountDailyReport).where(
            AccountDailyReport.account_id == account_id,
            AccountDailyReport.report_date == report_date,
        )
    )


def _reset_hourly_projection(db: Session, *, account_id: int, report_date: date) -> None:
    db.execute(
        delete(SiteHourlyReport).where(
            SiteHourlyReport.account_id == account_id,
            SiteHourlyReport.report_date == report_date,
        )
    )
    db.execute(
        delete(AccountHourlyReport).where(
            AccountHourlyReport.account_id == account_id,
            AccountHourlyReport.report_date == report_date,
        )
    )


def _rebuild_account_hourly_reports(db: Session, *, account_id: int, report_date: date) -> None:
    db.execute(
        delete(AccountHourlyReport).where(
            AccountHourlyReport.account_id == account_id,
            AccountHourlyReport.report_date == report_date,
        )
    )

    site_rows = list(
        db.scalars(
            select(SiteHourlyReport).where(
                SiteHourlyReport.account_id == account_id,
                SiteHourlyReport.report_date == report_date,
            )
        )
    )
    grouped: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in site_rows:
        normalized_report_time = service._serialize_utc_datetime(row.report_time_utc)
        key = (normalized_report_time.isoformat(), row.ad_country_code, row.ad_slot_id)
        if key not in grouped:
            grouped[key] = {
                "report_date": row.report_date,
                "hour": row.hour,
                "report_time_utc": normalized_report_time,
                "source_timezone": row.source_timezone,
                "currency": row.currency,
                "ad_country_code": row.ad_country_code,
                "ad_country_name": row.ad_country_name,
                "ad_slot_id": row.ad_slot_id,
                "ad_slot_name": row.ad_slot_name,
                "responses_served": 0,
                "requests": 0,
                "impressions": 0,
                "clicks": 0,
                "revenue": Decimal("0"),
            }
        grouped_row = grouped[key]
        grouped_row["responses_served"] += row.responses_served
        grouped_row["requests"] += row.requests
        grouped_row["impressions"] += row.impressions
        grouped_row["clicks"] += row.clicks
        grouped_row["revenue"] += row.revenue

    for grouped_row in grouped.values():
        db.add(
            AccountHourlyReport(
                account_id=account_id,
                report_date=grouped_row["report_date"],
                hour=grouped_row["hour"],
                report_time_utc=grouped_row["report_time_utc"],
                source_timezone=grouped_row["source_timezone"],
                currency=grouped_row["currency"],
                ad_country_code=grouped_row["ad_country_code"],
                ad_country_name=grouped_row["ad_country_name"],
                ad_slot_id=grouped_row["ad_slot_id"],
                ad_slot_name=grouped_row["ad_slot_name"],
                responses_served=grouped_row["responses_served"],
                requests=grouped_row["requests"],
                impressions=grouped_row["impressions"],
                clicks=grouped_row["clicks"],
                revenue=grouped_row["revenue"].quantize(Decimal("0.000001")),
                ecpm=_calculate_ecpm(
                    revenue=grouped_row["revenue"],
                    impressions=grouped_row["impressions"],
                ),
            )
        )


def _rebuild_site_daily_reports_from_hourly(db: Session, *, account_id: int, report_date: date) -> None:
    _reset_daily_projection(db, account_id=account_id, report_date=report_date)

    site_rows = list(
        db.scalars(
            select(SiteHourlyReport).where(
                SiteHourlyReport.account_id == account_id,
                SiteHourlyReport.report_date == report_date,
            )
        )
    )
    grouped: dict[str, dict[str, Any]] = {}
    for row in site_rows:
        if row.url_id not in grouped:
            grouped[row.url_id] = {
                "url": row.url,
                "responses_served": 0,
                "requests": 0,
                "impressions": 0,
                "clicks": 0,
                "revenue": Decimal("0"),
            }
        grouped_row = grouped[row.url_id]
        grouped_row["responses_served"] += row.responses_served
        grouped_row["requests"] += row.requests
        grouped_row["impressions"] += row.impressions
        grouped_row["clicks"] += row.clicks
        grouped_row["revenue"] += row.revenue

    for url_id, grouped_row in grouped.items():
        impressions = grouped_row["impressions"]
        revenue = grouped_row["revenue"].quantize(Decimal("0.000001"))
        db.add(
            SiteDailyReport(
                account_id=account_id,
                report_date=report_date,
                url_id=url_id,
                url=grouped_row["url"],
                responses_served=grouped_row["responses_served"],
                requests=grouped_row["requests"],
                impressions=impressions,
                clicks=grouped_row["clicks"],
                revenue=revenue,
                ecpm=_calculate_ecpm(revenue=revenue, impressions=impressions),
            )
        )
    db.flush()


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
    requests = sum(row.requests for row in rows)
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
    existing.requests = requests
    existing.impressions = impressions
    existing.clicks = clicks
    existing.revenue = revenue.quantize(Decimal("0.000001"))
    existing.ecpm = ecpm


def _calculate_ecpm(*, revenue: Decimal, impressions: int) -> Decimal:
    if impressions <= 0:
        return Decimal("0.000000")
    ecpm = (revenue * Decimal("1000")) / Decimal(impressions)
    return ecpm.quantize(Decimal("0.000001"))


def _parse_report_time_utc(value: Any) -> datetime:
    normalized = str(value).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
