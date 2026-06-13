from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from secrets import token_urlsafe

import httpx
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
        report_base_url=payload.report_base_url.rstrip("/") if payload.report_base_url else None,
        report_account_key=payload.report_account_key,
        report_token=payload.report_token,
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


def list_mid_platform_link_resources(
    db: Session,
    *,
    account_id: int | None = None,
) -> list[schemas.MidPlatformLinkResource]:
    query = (
        select(Account, CollectorInstance, SiteDailyReport.url, SiteDailyReport.url_id)
        .join(CollectorInstance, CollectorInstance.account_id == Account.id)
        .join(SiteDailyReport, SiteDailyReport.account_id == Account.id)
        .order_by(Account.id, CollectorInstance.id, SiteDailyReport.url, SiteDailyReport.url_id)
    )
    if account_id is not None:
        query = query.where(Account.id == account_id)

    rows = db.execute(query).all()
    seen: set[tuple[int, int, str, str]] = set()
    items: list[schemas.MidPlatformLinkResource] = []
    for account, instance, site_name, link_key in rows:
        dedupe_key = (account.id, instance.id, str(site_name), str(link_key))
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        items.append(
            schemas.MidPlatformLinkResource(
                account_id=account.id,
                account_name=account.name,
                instance_id=instance.id,
                instance_name=instance.name,
                node_base_url=instance.report_base_url or "",
                node_account_key=instance.report_account_key or instance.name,
                site_name=str(site_name),
                link_key=str(link_key),
                link_name=str(link_key),
                destination_url=None,
                status="active",
            )
        )
    return items


def list_mid_platform_account_resources(
    db: Session,
    *,
    account_id: int | None = None,
) -> list[schemas.MidPlatformAccountResource]:
    query = (
        select(Account, CollectorInstance)
        .join(CollectorInstance, CollectorInstance.account_id == Account.id)
        .order_by(Account.id, CollectorInstance.id)
    )
    if account_id is not None:
        query = query.where(Account.id == account_id)

    rows = db.execute(query).all()
    items: list[schemas.MidPlatformAccountResource] = []
    seen: set[int] = set()
    for account, instance in rows:
        if account.id in seen:
            continue
        seen.add(account.id)
        items.append(
            schemas.MidPlatformAccountResource(
                account_id=account.id,
                account_name=account.name,
                external_account_key=instance.report_account_key or instance.name,
                network_code=account.external_account_id,
                status="active",
            )
        )
    return items


def list_mid_platform_node_resources(
    db: Session,
    *,
    account_id: int | None = None,
) -> list[schemas.MidPlatformNodeResource]:
    query = (
        select(Account, CollectorInstance)
        .join(CollectorInstance, CollectorInstance.account_id == Account.id)
        .order_by(Account.id, CollectorInstance.id)
    )
    if account_id is not None:
        query = query.where(Account.id == account_id)

    rows = db.execute(query).all()
    return [
        schemas.MidPlatformNodeResource(
            account_id=account.id,
            account_name=account.name,
            instance_id=instance.id,
            instance_name=instance.name,
            node_base_url=instance.report_base_url or "",
            node_account_key=instance.report_account_key or instance.name,
            status="active",
        )
        for account, instance in rows
    ]


def list_mid_platform_site_resources(
    db: Session,
    *,
    account_id: int | None = None,
) -> list[schemas.MidPlatformSiteResource]:
    query = (
        select(Account, CollectorInstance, SiteDailyReport.url)
        .join(CollectorInstance, CollectorInstance.account_id == Account.id)
        .join(SiteDailyReport, SiteDailyReport.account_id == Account.id)
        .order_by(Account.id, CollectorInstance.id, SiteDailyReport.url)
    )
    if account_id is not None:
        query = query.where(Account.id == account_id)

    rows = db.execute(query).all()
    items: list[schemas.MidPlatformSiteResource] = []
    seen: set[tuple[int, int, str]] = set()
    for account, instance, site_name in rows:
        dedupe_key = (account.id, instance.id, str(site_name))
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        items.append(
            schemas.MidPlatformSiteResource(
                account_id=account.id,
                account_name=account.name,
                instance_id=instance.id,
                instance_name=instance.name,
                node_base_url=instance.report_base_url or "",
                node_account_key=instance.report_account_key or instance.name,
                site_name=str(site_name),
                status="active",
            )
        )
    return items


def list_mid_platform_site_daily_report(
    db: Session,
    *,
    report_date: date,
    account_id: int | None = None,
    timeout_seconds: int = 15,
) -> schemas.MidPlatformSiteDailyReportResponse:
    successful_snapshots, node_results = _collect_remote_node_snapshots(
        db,
        report_date=report_date,
        account_id=account_id,
        timeout_seconds=timeout_seconds,
    )
    items: list[schemas.MidPlatformSiteDailyRow] = []
    total_responses_served = 0
    total_impressions = 0
    total_clicks = 0
    total_revenue = Decimal("0")

    for snapshot in successful_snapshots:
        run_id = int(snapshot["run_id"])
        for row in snapshot["items"]:
            site_row = schemas.MidPlatformSiteDailyRow(
                account_id=snapshot["account_id"],
                account_name=snapshot["account_name"],
                instance_id=snapshot["instance_id"],
                instance_name=snapshot["instance_name"],
                node_base_url=snapshot["node_base_url"],
                node_account_key=snapshot["node_account_key"],
                report_date=report_date,
                site_name=str(row["site_name"]),
                responses_served=int(row["responses_served"]),
                impressions=int(row["impressions"]),
                clicks=int(row["clicks"]),
                revenue=float(_parse_decimal(row["revenue"], "site revenue")),
                ecpm=float(_parse_decimal(row["ecpm"], "site ecpm")),
                source_run_id=run_id,
            )
            items.append(site_row)
            total_responses_served += site_row.responses_served
            total_impressions += site_row.impressions
            total_clicks += site_row.clicks
            total_revenue += Decimal(str(site_row.revenue))

    summary = _build_mid_platform_summary(
        report_date=report_date,
        node_results=node_results,
        row_count=len(items),
        total_responses_served=total_responses_served,
        total_impressions=total_impressions,
        total_clicks=total_clicks,
        total_revenue=total_revenue,
    )
    return schemas.MidPlatformSiteDailyReportResponse(
        report_date=report_date,
        summary=summary,
        node_results=node_results,
        items=items,
    )


def list_mid_platform_link_daily_report(
    db: Session,
    *,
    report_date: date,
    account_id: int | None = None,
) -> schemas.MidPlatformLinkDailyReportResponse:
    query = (
        select(Account, CollectorInstance, SiteDailyReport)
        .join(CollectorInstance, CollectorInstance.account_id == Account.id)
        .join(SiteDailyReport, SiteDailyReport.account_id == Account.id)
        .where(SiteDailyReport.report_date == report_date)
        .order_by(Account.id, CollectorInstance.id, SiteDailyReport.url, SiteDailyReport.url_id)
    )
    if account_id is not None:
        query = query.where(Account.id == account_id)

    rows = db.execute(query).all()
    items: list[schemas.MidPlatformLinkDailyRow] = []
    total_responses_served = 0
    total_impressions = 0
    total_clicks = 0
    total_revenue = Decimal("0")
    node_index: dict[int, schemas.MidPlatformNodeResult] = {}

    for account, instance, site_report in rows:
        if instance.id not in node_index:
            node_index[instance.id] = schemas.MidPlatformNodeResult(
                account_id=account.id,
                account_name=account.name,
                instance_id=instance.id,
                instance_name=instance.name,
                node_base_url=instance.report_base_url or "",
                node_account_key=instance.report_account_key or instance.name,
                source_state="success",
                source_http_status=200,
                source_run_id=None,
                row_count=0,
                message=None,
            )

        row = schemas.MidPlatformLinkDailyRow(
            account_id=account.id,
            account_name=account.name,
            instance_id=instance.id,
            instance_name=instance.name,
            node_base_url=instance.report_base_url or "",
            node_account_key=instance.report_account_key or instance.name,
            report_date=site_report.report_date,
            site_name=site_report.url,
            link_key=site_report.url_id,
            responses_served=site_report.responses_served,
            impressions=site_report.impressions,
            clicks=site_report.clicks,
            revenue=float(site_report.revenue),
            ecpm=float(site_report.ecpm),
            source_run_id=None,
        )
        items.append(row)
        node_index[instance.id].row_count += 1
        total_responses_served += row.responses_served
        total_impressions += row.impressions
        total_clicks += row.clicks
        total_revenue += Decimal(str(row.revenue))

    node_results = list(node_index.values())
    summary = _build_mid_platform_summary(
        report_date=report_date,
        node_results=node_results,
        row_count=len(items),
        total_responses_served=total_responses_served,
        total_impressions=total_impressions,
        total_clicks=total_clicks,
        total_revenue=total_revenue,
    )
    return schemas.MidPlatformLinkDailyReportResponse(
        report_date=report_date,
        summary=summary,
        node_results=node_results,
        items=items,
    )


def list_mid_platform_account_daily_report(
    db: Session,
    *,
    report_date: date,
    account_id: int | None = None,
    timeout_seconds: int = 15,
) -> schemas.MidPlatformAccountDailyReportResponse:
    successful_snapshots, node_results = _collect_remote_node_snapshots(
        db,
        report_date=report_date,
        account_id=account_id,
        timeout_seconds=timeout_seconds,
    )
    items: list[schemas.MidPlatformAccountDailyRow] = []
    total_responses_served = 0
    total_impressions = 0
    total_clicks = 0
    total_revenue = Decimal("0")

    for snapshot in successful_snapshots:
        rows = snapshot["items"]
        responses_served = sum(int(row["responses_served"]) for row in rows)
        impressions = sum(int(row["impressions"]) for row in rows)
        clicks = sum(int(row["clicks"]) for row in rows)
        revenue = sum((_parse_decimal(row["revenue"], "account revenue") for row in rows), start=Decimal("0"))
        ecpm = Decimal("0")
        if impressions > 0:
            ecpm = ((revenue * Decimal("1000")) / Decimal(impressions)).quantize(Decimal("0.000001"))

        account_row = schemas.MidPlatformAccountDailyRow(
            account_id=snapshot["account_id"],
            account_name=snapshot["account_name"],
            instance_id=snapshot["instance_id"],
            instance_name=snapshot["instance_name"],
            node_base_url=snapshot["node_base_url"],
            node_account_key=snapshot["node_account_key"],
            report_date=report_date,
            site_count=len(rows),
            responses_served=responses_served,
            impressions=impressions,
            clicks=clicks,
            revenue=float(revenue),
            ecpm=float(ecpm),
            source_run_id=int(snapshot["run_id"]),
        )
        items.append(account_row)
        total_responses_served += responses_served
        total_impressions += impressions
        total_clicks += clicks
        total_revenue += revenue

    summary = _build_mid_platform_summary(
        report_date=report_date,
        node_results=node_results,
        row_count=len(items),
        total_responses_served=total_responses_served,
        total_impressions=total_impressions,
        total_clicks=total_clicks,
        total_revenue=total_revenue,
    )
    return schemas.MidPlatformAccountDailyReportResponse(
        report_date=report_date,
        summary=summary,
        node_results=node_results,
        items=items,
    )


def _configured_mid_platform_instances(db: Session, *, account_id: int | None = None) -> list[CollectorInstance]:
    query = (
        select(CollectorInstance)
        .where(
            CollectorInstance.report_base_url.is_not(None),
            CollectorInstance.report_account_key.is_not(None),
            CollectorInstance.report_token.is_not(None),
        )
        .order_by(CollectorInstance.id)
    )
    if account_id is not None:
        query = query.where(CollectorInstance.account_id == account_id)
    return list(db.scalars(query))


def _collect_remote_node_snapshots(
    db: Session,
    *,
    report_date: date,
    account_id: int | None,
    timeout_seconds: int,
) -> tuple[list[dict[str, object]], list[schemas.MidPlatformNodeResult]]:
    successful_snapshots: list[dict[str, object]] = []
    node_results: list[schemas.MidPlatformNodeResult] = []

    for instance in _configured_mid_platform_instances(db, account_id=account_id):
        account = db.get(Account, instance.account_id)
        if account is None or not instance.report_base_url or not instance.report_account_key or not instance.report_token:
            continue

        node_result = schemas.MidPlatformNodeResult(
            account_id=account.id,
            account_name=account.name,
            instance_id=instance.id,
            instance_name=instance.name,
            node_base_url=instance.report_base_url,
            node_account_key=instance.report_account_key,
            source_state="error",
            source_http_status=None,
            source_run_id=None,
            row_count=0,
            message=None,
        )
        try:
            response = httpx.get(
                f"{instance.report_base_url}/ke/report.php",
                params={
                    "account_key": instance.report_account_key,
                    "report_date": report_date.isoformat(),
                    "token": instance.report_token,
                },
                timeout=timeout_seconds,
            )
            node_result.source_http_status = response.status_code
            if response.status_code != 200:
                node_result.message = f"remote report returned HTTP {response.status_code}"
                node_results.append(node_result)
                continue

            payload = response.json()
            if payload.get("ok") is not True:
                node_result.message = str(
                    payload.get("message") or payload.get("error_message") or "remote report returned ok=false"
                )
                node_results.append(node_result)
                continue
            if payload.get("account_key") != instance.report_account_key:
                node_result.message = "remote report account_key mismatch"
                node_results.append(node_result)
                continue
            if payload.get("report_date") != report_date.isoformat():
                node_result.message = "remote report report_date mismatch"
                node_results.append(node_result)
                continue
            if payload.get("has_run") is not True or payload.get("run_status") != "success":
                node_result.source_state = "no_snapshot"
                node_result.row_count = int(payload.get("row_count") or 0)
                node_results.append(node_result)
                continue

            rows = payload.get("items")
            run_id = payload.get("run_id")
            if not isinstance(rows, list):
                node_result.message = "remote report items is not a list"
                node_results.append(node_result)
                continue
            if run_id is None:
                node_result.message = "remote report run_id is missing"
                node_results.append(node_result)
                continue

            successful_snapshots.append(
                {
                    "account_id": account.id,
                    "account_name": account.name,
                    "instance_id": instance.id,
                    "instance_name": instance.name,
                    "node_base_url": instance.report_base_url,
                    "node_account_key": instance.report_account_key,
                    "run_id": int(run_id),
                    "items": rows,
                }
            )
            node_result.source_state = "success"
            node_result.source_run_id = int(run_id)
            node_result.row_count = int(payload.get("row_count") or len(rows))
            node_results.append(node_result)
        except (httpx.HTTPError, ValueError, TypeError, InvalidOperation) as exc:
            node_result.message = str(exc)
            node_results.append(node_result)

    return successful_snapshots, node_results


def _build_mid_platform_summary(
    *,
    report_date: date,
    node_results: list[schemas.MidPlatformNodeResult],
    row_count: int,
    total_responses_served: int,
    total_impressions: int,
    total_clicks: int,
    total_revenue: Decimal,
) -> schemas.MidPlatformSummary:
    return schemas.MidPlatformSummary(
        report_date=report_date,
        requested_node_count=len(node_results),
        success_node_count=sum(1 for item in node_results if item.source_state == "success"),
        no_snapshot_node_count=sum(1 for item in node_results if item.source_state == "no_snapshot"),
        error_node_count=sum(1 for item in node_results if item.source_state == "error"),
        row_count=row_count,
        total_responses_served=total_responses_served,
        total_impressions=total_impressions,
        total_clicks=total_clicks,
        total_revenue=float(total_revenue),
    )


def _parse_decimal(value: object, label: str) -> Decimal:
    try:
        return Decimal(str(value)).quantize(Decimal("0.000001"))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"invalid {label}") from exc


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
