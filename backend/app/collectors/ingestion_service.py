from __future__ import annotations

import json
import hashlib
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.collectors import schemas, service
from app.models.account import Account
from app.models.account_daily_report import AccountDailyReport
from app.models.account_daily_dimension_report import AccountDailyDimensionReport
from app.models.account_hourly_report import AccountHourlyReport
from app.models.collector_ingestion_batch import CollectorIngestionBatch
from app.models.collector_instance import CollectorInstance
from app.models.collector_sync_task import CollectorSyncTask
from app.models.site_daily_report import SiteDailyReport
from app.models.site_daily_dimension_report import SiteDailyDimensionReport
from app.models.site_hourly_report import SiteHourlyReport
from app.models.authoritative_daily_version_summary import AuthoritativeDailyVersionSummary


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
    if payload.schema_version == "admanager_authoritative_daily_v1":
        if not payload.rows or len(payload.rows) != 1:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid authoritative daily snapshot")
        core_rows = payload.rows[0].get("core_rows")
        dimension_rows = payload.rows[0].get("dimension_rows")
        if not isinstance(core_rows, list) or not isinstance(dimension_rows, list):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Authoritative daily snapshot requires core_rows and dimension_rows")
        actual_row_count = len(core_rows) + len(dimension_rows)
        actual_payload_hash = hashlib.sha256(
            json.dumps(payload.rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if payload.row_count != actual_row_count or payload.payload_hash != actual_payload_hash:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Authoritative daily row_count or payload_hash mismatch")
    if payload.schema_version == "admanager_authoritative_daily_v1":
        # Serialize publications for one account. On SQLite this acquires the
        # database write lock; on PostgreSQL it locks the account row.
        db.execute(
            update(Account)
            .where(Account.id == task.account_id)
            .values(updated_at=Account.updated_at)
        )
        published_slot = db.scalar(
            select(func.max(AuthoritativeDailyVersionSummary.slot)).where(
                AuthoritativeDailyVersionSummary.account_id == task.account_id,
                AuthoritativeDailyVersionSummary.report_date == task.report_date,
            )
        )
        task_slot = task.authoritative_slot or 0
        if published_slot is not None and published_slot > task_slot:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A later authoritative daily slot has already been published",
            )

    payload_json = json.dumps(payload.rows, separators=(",", ":"), sort_keys=True) if payload.rows is not None else None
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

    # A report task can emit more than one schema.  Each schema owns an
    # independent snapshot, so the first batch must be determined per schema
    # instead of per task (core rows are uploaded before daily dimensions).
    is_first_batch_for_schema = db.scalar(
        select(CollectorIngestionBatch.id).where(
            CollectorIngestionBatch.task_id == task_id,
            CollectorIngestionBatch.schema_version == payload.schema_version,
        ).limit(1)
    ) is None

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
            reset_existing=is_first_batch_for_schema,
        )
        if payload.schema_version == "admanager_authoritative_daily_v1":
            account_daily = db.scalar(
                select(AccountDailyReport).where(
                    AccountDailyReport.account_id == task.account_id,
                    AccountDailyReport.report_date == task.report_date,
                )
            )
            db.add(AuthoritativeDailyVersionSummary(
                task_id=task.id,
                account_id=task.account_id,
                report_date=task.report_date,
                slot=task.authoritative_slot,
                responses_served=account_daily.responses_served if account_daily else 0,
                requests=account_daily.requests if account_daily else 0,
                impressions=account_daily.impressions if account_daily else 0,
                clicks=account_daily.clicks if account_daily else 0,
                revenue=account_daily.revenue if account_daily else Decimal("0"),
                row_count=payload.row_count,
                payload_hash=payload.payload_hash,
            ))
            prior_task_ids = select(AuthoritativeDailyVersionSummary.task_id).where(
                AuthoritativeDailyVersionSummary.account_id == task.account_id,
                AuthoritativeDailyVersionSummary.report_date == task.report_date,
                AuthoritativeDailyVersionSummary.task_id != task.id,
            )
            db.execute(
                update(CollectorIngestionBatch)
                .where(
                    CollectorIngestionBatch.task_id.in_(prior_task_ids),
                    CollectorIngestionBatch.schema_version == "admanager_authoritative_daily_v1",
                )
                .values(payload_json=None)
            )
            task.status = "succeeded"
            task.finished_at = datetime.now(timezone.utc)
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
    if schema_version == "admanager_authoritative_daily_v1":
        if task.task_type != "report_fetch" or len(rows) != 1:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid authoritative daily snapshot",
            )
        envelope = rows[0]
        core_rows = envelope.get("core_rows")
        dimension_rows = envelope.get("dimension_rows")
        if not isinstance(core_rows, list) or not isinstance(dimension_rows, list):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Authoritative daily snapshot requires core_rows and dimension_rows",
            )
        _project_payload_if_supported(
            db,
            task=task,
            schema_version="admanager_site_core_v1",
            rows=core_rows,
            reset_existing=True,
        )
        if not core_rows:
            _reset_daily_projection(db, account_id=task.account_id, report_date=task.report_date)
        _project_payload_if_supported(
            db,
            task=task,
            schema_version="admanager_daily_dimension_v1",
            rows=dimension_rows,
            reset_existing=True,
        )
        if not dimension_rows:
            _reset_daily_dimension_projection(db, account_id=task.account_id, report_date=task.report_date)
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
        return

    if schema_version == "admanager_daily_dimension_v1":
        account = db.get(Account, task.account_id)
        if account is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
        normalized_rows = [
            _normalize_admanager_daily_dimension_row(row, report_date=task.report_date, account=account)
            for row in rows
        ]
        if reset_existing:
            _reset_daily_dimension_projection(
                db,
                account_id=task.account_id,
                report_date=task.report_date,
            )
        for row in normalized_rows:
            existing = db.scalar(
                select(SiteDailyDimensionReport).where(
                    SiteDailyDimensionReport.account_id == task.account_id,
                    SiteDailyDimensionReport.report_date == task.report_date,
                    SiteDailyDimensionReport.url_id == row["url_id"],
                    SiteDailyDimensionReport.ad_country_code == row["ad_country_code"],
                    SiteDailyDimensionReport.ad_slot_id == row["ad_slot_id"],
                    SiteDailyDimensionReport.source_kind == "authoritative_daily",
                )
            )
            if existing is None:
                existing = SiteDailyDimensionReport(
                    account_id=task.account_id,
                    report_date=task.report_date,
                    url_id=row["url_id"],
                    ad_country_code=row["ad_country_code"],
                    ad_slot_id=row["ad_slot_id"],
                    source_kind="authoritative_daily",
                )
                db.add(existing)
            for key, value in row.items():
                setattr(existing, key, value)
            existing.source_kind = "authoritative_daily"
            existing.coverage_hours = row["expected_hours"]
            existing.is_complete = True
        db.flush()
        _rebuild_account_daily_dimension_reports(db, account_id=task.account_id, report_date=task.report_date)
        return


def _normalize_admanager_daily_dimension_row(row: dict[str, Any], *, report_date: date, account: Account) -> dict[str, Any]:
    if date.fromisoformat(str(row.get("report_date"))) != report_date:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Batch row report_date mismatch")
    try:
        # Authoritative daily rows are keyed by the account's configured GAM
        # report timezone.  A civil day can contain 23 or 25 hours at DST
        # boundaries, so a constant 24 would produce false completeness.
        expected_hours = service._expected_hours_for_timezone(report_date, account.timezone)
        return {"url_id": str(row["url_id"]), "url": str(row["url"]), "ad_country_code": str(row.get("ad_country_code") or "UNKNOWN"), "ad_country_name": str(row.get("ad_country_name") or "UNKNOWN"), "ad_slot_id": str(row.get("ad_slot_id") or "UNKNOWN"), "ad_slot_name": str(row.get("ad_slot_name") or "UNKNOWN"), "currency": account.currency, "responses_served": int(row["responses_served"]), "requests": int(row.get("requests", 0)), "impressions": int(row["impressions"]), "clicks": int(row["clicks"]), "revenue": Decimal(str(row["revenue"])), "ecpm": Decimal(str(row["ecpm"])), "expected_hours": expected_hours}
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Batch rows do not match admanager_daily_dimension_v1 schema") from exc


def _rebuild_account_daily_dimension_reports(db: Session, *, account_id: int, report_date: date) -> None:
    db.execute(delete(AccountDailyDimensionReport).where(AccountDailyDimensionReport.account_id == account_id, AccountDailyDimensionReport.report_date == report_date, AccountDailyDimensionReport.source_kind == "authoritative_daily"))
    rows = db.scalars(select(SiteDailyDimensionReport).where(SiteDailyDimensionReport.account_id == account_id, SiteDailyDimensionReport.report_date == report_date, SiteDailyDimensionReport.source_kind == "authoritative_daily")).all()
    grouped: dict[tuple[str, str], list[Any]] = {}
    for row in rows: grouped.setdefault((row.ad_country_code, row.ad_slot_id), []).append(row)
    for (_, _), values in grouped.items():
        first = values[0]; revenue = sum((value.revenue for value in values), Decimal("0")); impressions = sum(value.impressions for value in values)
        db.add(AccountDailyDimensionReport(account_id=account_id, report_date=report_date, ad_country_code=first.ad_country_code, ad_country_name=first.ad_country_name, ad_slot_id=first.ad_slot_id, ad_slot_name=first.ad_slot_name, source_kind="authoritative_daily", currency=first.currency, responses_served=sum(value.responses_served for value in values), requests=sum(value.requests for value in values), impressions=impressions, clicks=sum(value.clicks for value in values), revenue=revenue, ecpm=_calculate_ecpm(revenue=revenue, impressions=impressions), coverage_hours=first.coverage_hours, expected_hours=first.expected_hours, is_complete=True))


def _normalize_admanager_site_row(row: dict[str, Any], report_date: date) -> dict[str, Any]:
    row_report_date = row.get("report_date")
    if row_report_date is None or date.fromisoformat(str(row_report_date)) != report_date:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Batch row report_date mismatch")
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
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Batch rows do not match admanager_site_core_v1 schema") from exc


def _normalize_admanager_hourly_site_row(
    row: dict[str, Any],
    *,
    report_date: date,
    account: Account,
) -> dict[str, Any]:
    row_report_date = row.get("report_date")
    if row_report_date is None or date.fromisoformat(str(row_report_date)) != report_date:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Batch row report_date mismatch")

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
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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


def _reset_daily_dimension_projection(db: Session, *, account_id: int, report_date: date) -> None:
    """Clear the authoritative daily-dimension snapshot before its first page."""
    db.execute(
        delete(SiteDailyDimensionReport).where(
            SiteDailyDimensionReport.account_id == account_id,
            SiteDailyDimensionReport.report_date == report_date,
            SiteDailyDimensionReport.source_kind == "authoritative_daily",
        )
    )
    db.execute(
        delete(AccountDailyDimensionReport).where(
            AccountDailyDimensionReport.account_id == account_id,
            AccountDailyDimensionReport.report_date == report_date,
            AccountDailyDimensionReport.source_kind == "authoritative_daily",
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
