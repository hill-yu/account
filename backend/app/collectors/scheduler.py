from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.collectors import schemas, service
from app.config import get_settings
from app.database import get_session_factory
from app.models.fetch_schedule import FetchSchedule


STALE_IN_PROGRESS_TASK_AGE = timedelta(hours=2)
CROSS_DAY_FINALIZE_START_HOUR = 1
CROSS_DAY_FINALIZE_END_HOUR = 3
CROSS_DAY_FINALIZE_MAX_ATTEMPTS = 2


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def compute_next_run_at(
    *,
    mode: str,
    timezone_name: str,
    now: datetime,
    daily_times: list[str] | None,
    interval_hours: int | None,
    last_triggered_at: datetime | None,
) -> datetime:
    if mode == "daily_times":
        return compute_daily_times_next_run(
            timezone_name=timezone_name,
            now=now,
            daily_times=daily_times or [],
        )
    if mode == "interval_hours":
        return compute_interval_hours_next_run(
            now=now,
            interval_hours=interval_hours,
            last_triggered_at=last_triggered_at,
        )
    raise ValueError(f"Unsupported fetch schedule mode: {mode}")


def compute_daily_times_next_run(
    *,
    timezone_name: str,
    now: datetime,
    daily_times: list[str],
) -> datetime:
    if not daily_times:
        raise ValueError("daily_times must not be empty")

    zone = ZoneInfo(timezone_name)
    local_now = _ensure_aware(now).astimezone(zone)
    parsed_times = sorted(_parse_daily_time(value) for value in daily_times)

    for hour, minute in parsed_times:
        candidate = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate > local_now:
            return candidate.astimezone(timezone.utc)

    next_day = local_now + timedelta(days=1)
    first_hour, first_minute = parsed_times[0]
    return next_day.replace(hour=first_hour, minute=first_minute, second=0, microsecond=0).astimezone(timezone.utc)


def compute_interval_hours_next_run(
    *,
    now: datetime,
    interval_hours: int | None,
    last_triggered_at: datetime | None,
) -> datetime:
    if interval_hours is None or interval_hours <= 0:
        raise ValueError("interval_hours must be a positive integer")

    anchor = _ensure_aware(last_triggered_at or now)
    return anchor + timedelta(hours=interval_hours)


class FetchScheduler:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session] | None = None,
        trigger_manual_fetch: Callable[..., schemas.ManualFetchResponse] | None = None,
        timeout_seconds: int = 15,
        now_provider: Callable[[], datetime] = utcnow,
    ) -> None:
        self._session_factory = session_factory or get_session_factory()
        self._trigger_manual_fetch = trigger_manual_fetch or service.trigger_manual_fetch
        self._timeout_seconds = timeout_seconds
        self._now_provider = now_provider

    def run_pending_once(self) -> int:
        now = _ensure_aware(self._now_provider())
        processed = 0

        with self._session_factory() as db:
            service.fail_stale_in_progress_tasks(
                db,
                stale_before=now - STALE_IN_PROGRESS_TASK_AGE,
                finished_at=now,
            )
            due_schedules = list(
                db.scalars(
                    select(FetchSchedule)
                    .where(
                        FetchSchedule.enabled.is_(True),
                        FetchSchedule.next_run_at.is_not(None),
                        FetchSchedule.next_run_at <= now,
                    )
                    .order_by(FetchSchedule.next_run_at.asc(), FetchSchedule.id.asc())
                )
            )

            for schedule in due_schedules:
                local_now = now.astimezone(ZoneInfo(schedule.timezone))
                source_now = now.astimezone(ZoneInfo(service.DEFAULT_REPORT_TIMEZONE))
                schedule.last_triggered_at = now
                report_date = local_now.date()
                run_reason = "preview"
                external_request_id = None
                instance = schedule.collector_instance
                enabled_account_keys = {
                    item.strip()
                    for item in get_settings().cross_day_finalize_account_keys.split(",")
                    if item.strip()
                }
                if (
                    instance is not None
                    and get_settings().direct_collector_only
                    and instance.report_account_key in enabled_account_keys
                    and CROSS_DAY_FINALIZE_START_HOUR <= source_now.hour < CROSS_DAY_FINALIZE_END_HOUR
                ):
                    previous_report_date = source_now.date() - timedelta(days=1)
                    attempts = service.list_cross_day_finalize_attempts(
                        db,
                        account_id=schedule.account_id,
                        report_date=previous_report_date,
                    )
                    if not any(task.status in {"succeeded", "blocked"} for task in attempts):
                        active_attempt = next(
                            (task for task in attempts if task.status in {"pending", "in_progress"}),
                            None,
                        )
                        failed_count = sum(task.status in {"failed", "cancelled"} for task in attempts)
                        if active_attempt is not None or failed_count < CROSS_DAY_FINALIZE_MAX_ATTEMPTS:
                            report_date = previous_report_date
                            run_reason = "cross_day_finalize"
                            external_request_id = (
                                f"hourly-finalize-{schedule.account_id}-{report_date.isoformat()}-{failed_count + 1}"
                            )
                        else:
                            service.record_cross_day_finalize_exhausted(
                                db,
                                account_id=schedule.account_id,
                                collector_instance_id=schedule.collector_instance_id,
                                report_date=previous_report_date,
                            )
                try:
                    trigger_kwargs = {
                        "timeout_seconds": self._timeout_seconds,
                        "fetch_kind": "automatic_hourly",
                        "direct_collector_only": get_settings().direct_collector_only,
                    }
                    if run_reason == "cross_day_finalize":
                        trigger_kwargs.update(
                            run_reason=run_reason,
                            external_request_id=external_request_id,
                        )
                    response = self._trigger_manual_fetch(
                        db,
                        schemas.ManualFetchRequest(
                            account_id=schedule.account_id,
                            collector_instance_id=schedule.collector_instance_id,
                            report_date=report_date,
                        ),
                        **trigger_kwargs,
                    )
                    schedule.last_trigger_status = response.status or ("accepted" if response.ok else "failed")
                    schedule.last_trigger_message = response.message
                except Exception as exc:  # noqa: BLE001
                    schedule.last_trigger_status = "failed"
                    schedule.last_trigger_message = _exception_message(exc)

                schedule.next_run_at = compute_next_run_at(
                    mode=schedule.mode,
                    timezone_name=schedule.timezone,
                    now=now,
                    daily_times=_load_daily_times(schedule.daily_times_json),
                    interval_hours=schedule.interval_hours,
                    last_triggered_at=schedule.last_triggered_at,
                )
                processed += 1

            recovery_task = service.enqueue_next_oauth_recovery_gap(db, now=now)
            if recovery_task is not None:
                recovery_instance = recovery_task.collector_instance
                # The collector runs in a separate process and must be able to
                # see the task before it starts claiming work.
                db.commit()
                try:
                    service._launch_hourly_sync_runtime(recovery_instance)
                except Exception:  # noqa: BLE001
                    recovery_task.status = "failed"
                    recovery_task.finished_at = now
                    db.commit()
                processed += 1

            processed += self._enqueue_due_authoritative_daily_fetches(db, now)
            db.commit()

        return processed

    def _enqueue_due_authoritative_daily_fetches(self, db: Session, now: datetime) -> int:
        processed = 0

        for instance in service.list_gray_daily_fetch_instances(db):
            if service.should_skip_automatic_data_fetch(db, instance, fetch_kind="automatic_daily"):
                continue

            account = instance.account
            if account is None:
                continue

            timezone_name = account.timezone or service.DEFAULT_REPORT_TIMEZONE
            local_now = now.astimezone(ZoneInfo(timezone_name))
            slot = local_now.hour if local_now.hour in {5, 6, 7} else None
            if slot is None:
                continue
            has_pending_task = False
            report_date = local_now.date() - timedelta(days=1)
            task, created = service._get_or_create_daily_sync_task(
                db,
                account_id=account.id,
                collector_instance_id=instance.id,
                report_date=report_date,
                authoritative_slot=slot,
                external_request_id=(
                    f"auto-daily-{instance.report_account_key}-{report_date.isoformat()}-{slot}-{token_urlsafe(6)}"
                ),
            )
            if task.status == "pending":
                has_pending_task = True
            if created:
                processed += 1

            # The collector runtime handles one task and exits. Relaunch it on
            # later scheduler passes while this instance still has queued work.
            if has_pending_task:
                service._launch_hourly_sync_runtime(instance)

        return processed


def _parse_daily_time(value: str) -> tuple[int, int]:
    hour_text, minute_text = value.split(":", maxsplit=1)
    hour = int(hour_text)
    minute = int(minute_text)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Invalid daily time: {value}")
    return hour, minute


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _load_daily_times(daily_times_json: str | None) -> list[str] | None:
    if daily_times_json is None:
        return None
    payload = json.loads(daily_times_json)
    return [str(item) for item in payload]


def _exception_message(exc: Exception) -> str:
    detail = getattr(exc, "detail", None)
    if detail is not None:
        return str(detail)
    return str(exc)
