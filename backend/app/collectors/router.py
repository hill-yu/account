from __future__ import annotations

from datetime import date
from hmac import compare_digest

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.collectors import ingestion_service, oauth_service, schemas, service
from app.collectors.security import (
    OPERATOR_SESSION_COOKIE,
    get_authenticated_instance,
    issue_operator_session,
    require_operator_authentication,
)
from app.config import get_settings
from app.database import get_db
from app.models.account import Account
from app.models.collector_instance import CollectorInstance


router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_operator_authentication)])
auth_router = APIRouter(prefix="/api/v1/operator/auth")


@auth_router.post("/login", response_model=schemas.OperatorSessionRead)
def login_operator(payload: schemas.OperatorLoginRequest, response: Response) -> schemas.OperatorSessionRead:
    settings = get_settings()
    if not settings.operator_api_token or not compare_digest(payload.password, settings.operator_api_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid operator token")
    response.set_cookie(
        key=OPERATOR_SESSION_COOKIE,
        value=issue_operator_session(),
        max_age=settings.operator_session_ttl_seconds,
        httponly=True,
        secure=settings.app_env == "production",
        samesite="strict",
        path="/",
    )
    return schemas.OperatorSessionRead(authenticated=True)


@auth_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout_operator() -> Response:
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(key=OPERATOR_SESSION_COOKIE, path="/", httponly=True, samesite="strict")
    return response


@auth_router.get("/session", response_model=schemas.OperatorSessionRead, dependencies=[Depends(require_operator_authentication)])
def get_operator_session() -> schemas.OperatorSessionRead:
    return schemas.OperatorSessionRead(authenticated=True)


@router.post("/operator/accounts", response_model=schemas.AccountRead, status_code=status.HTTP_201_CREATED)
def create_account(payload: schemas.AccountCreate, db: Session = Depends(get_db)) -> schemas.AccountRead:
    return service.create_account(db, payload)


@router.get("/operator/accounts", response_model=schemas.AccountList)
def list_accounts(db: Session = Depends(get_db)) -> schemas.AccountList:
    return schemas.AccountList(items=service.list_accounts(db))


@router.patch("/operator/accounts/{account_id}/timezone", response_model=schemas.AccountRead)
def update_account_timezone(
    account_id: int,
    payload: schemas.AccountTimezoneUpdate,
    db: Session = Depends(get_db),
) -> schemas.AccountRead:
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    account.timezone = payload.timezone
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


@router.post("/operator/oauth-apps", response_model=schemas.OAuthAppRead, status_code=status.HTTP_201_CREATED)
def create_oauth_app(payload: schemas.OAuthAppCreate, db: Session = Depends(get_db)) -> schemas.OAuthAppRead:
    return oauth_service.create_oauth_app(db, payload)


@router.get("/operator/oauth-apps", response_model=schemas.OAuthAppList)
def list_oauth_apps(db: Session = Depends(get_db)) -> schemas.OAuthAppList:
    return schemas.OAuthAppList(items=oauth_service.list_oauth_apps(db))


@router.get("/operator/oauth/health-summary", response_model=schemas.OAuthHealthSummary)
def get_oauth_health_summary(db: Session = Depends(get_db)) -> schemas.OAuthHealthSummary:
    return oauth_service.get_oauth_health_summary(db)


@router.post("/operator/oauth-apps/{oauth_app_id}/authorization-url", response_model=schemas.AuthorizationUrlResponse)
def generate_oauth_authorization_url(
    oauth_app_id: int,
    payload: schemas.AuthorizationUrlRequest | None = None,
    db: Session = Depends(get_db),
) -> schemas.AuthorizationUrlResponse:
    return oauth_service.generate_authorization_url(db, oauth_app_id, payload)


@router.post("/operator/oauth-apps/import-callback-json", response_model=schemas.OAuthCallbackResponse)
def import_oauth_callback_json(
    payload: schemas.OAuthCallbackImportRequest,
    db: Session = Depends(get_db),
) -> schemas.OAuthCallbackResponse:
    try:
        return oauth_service.import_google_callback_payload(db, payload)
    except oauth_service.OAuthStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth authorization state is invalid or expired",
        ) from exc


@router.post("/operator/instances", response_model=schemas.InstanceProvisionResponse, status_code=status.HTTP_201_CREATED)
def create_instance(payload: schemas.InstanceCreate, db: Session = Depends(get_db)) -> schemas.InstanceProvisionResponse:
    return service.create_instance(db, payload)


@router.get("/operator/instances", response_model=schemas.InstanceList)
def list_instances(db: Session = Depends(get_db)) -> schemas.InstanceList:
    return schemas.InstanceList(items=service.list_instances(db))


@router.post("/operator/proxies", response_model=schemas.ProxyBindingRead, status_code=status.HTTP_201_CREATED)
def create_proxy(payload: schemas.ProxyBindingCreate, db: Session = Depends(get_db)) -> schemas.ProxyBindingRead:
    return service.create_proxy_binding(db, payload)


@router.get("/operator/proxies", response_model=schemas.ProxyBindingList)
def list_proxies(db: Session = Depends(get_db)) -> schemas.ProxyBindingList:
    return schemas.ProxyBindingList(items=service.list_proxies(db))


@router.post("/operator/tasks", response_model=schemas.SyncTaskRead, status_code=status.HTTP_201_CREATED)
def create_task(payload: schemas.SyncTaskCreate, db: Session = Depends(get_db)) -> schemas.SyncTaskRead:
    return service.create_task(db, payload)


@router.get("/operator/tasks", response_model=schemas.SyncTaskList)
def list_tasks(db: Session = Depends(get_db)) -> schemas.SyncTaskList:
    return schemas.SyncTaskList(items=service.list_tasks(db))


@router.get("/operator/tasks/paged", response_model=schemas.PaginatedSyncTaskList)
def list_tasks_paged(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=200),
    snapshot_max_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
) -> schemas.PaginatedSyncTaskList:
    if page > 1 and snapshot_max_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="snapshot_max_id is required after the first page",
        )
    return service.list_tasks_page(
        db,
        page=page,
        page_size=page_size,
        snapshot_max_id=snapshot_max_id,
    )


@router.get("/operator/fetch-schedules", response_model=schemas.FetchScheduleList)
def list_fetch_schedules(db: Session = Depends(get_db)) -> schemas.FetchScheduleList:
    return schemas.FetchScheduleList(items=service.list_fetch_schedules(db))


@router.post(
    "/operator/fetch-schedules",
    response_model=schemas.FetchScheduleRead,
    status_code=status.HTTP_201_CREATED,
)
def create_fetch_schedule(
    payload: schemas.FetchScheduleCreate,
    db: Session = Depends(get_db),
) -> schemas.FetchScheduleRead:
    return service.create_or_replace_fetch_schedule(db, payload)


@router.patch("/operator/fetch-schedules/{schedule_id}", response_model=schemas.FetchScheduleRead)
def patch_fetch_schedule(
    schedule_id: int,
    payload: schemas.FetchScheduleUpdate,
    db: Session = Depends(get_db),
) -> schemas.FetchScheduleRead:
    return service.update_fetch_schedule(db, schedule_id, payload)


@router.post("/operator/fetch-schedules/manual-fetch", response_model=schemas.ManualFetchResponse)
def trigger_manual_fetch(
    payload: schemas.ManualFetchRequest,
    db: Session = Depends(get_db),
) -> schemas.ManualFetchResponse:
    settings = get_settings()
    return service.trigger_manual_fetch(
        db,
        payload,
        timeout_seconds=settings.operator_remote_report_timeout_seconds,
        direct_collector_only=settings.direct_collector_only,
    )


@router.post("/operator/hourly-backfill/targeted-recent", response_model=schemas.TargetedHourlyBackfillResponse)
def trigger_targeted_recent_hourly_backfill(
    payload: schemas.TargetedHourlyBackfillRequest,
    db: Session = Depends(get_db),
) -> schemas.TargetedHourlyBackfillResponse:
    return service.trigger_targeted_recent_hourly_backfill(db, payload)


@router.get("/operator/reports/account-daily", response_model=schemas.AccountDailyReportList)
def list_account_daily_reports(
    account_id: int | None = Query(default=None),
    report_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> schemas.AccountDailyReportList:
    items = service.list_account_daily_reports(db, account_id=account_id, report_date=report_date)
    return schemas.AccountDailyReportList(
        timezone=service.resolve_report_timezone(
            db,
            account_id=account_id,
            account_ids={item.account_id for item in items},
        ),
        coverage=service.build_hourly_coverage(db, account_id=account_id, report_date=report_date),
        items=items,
    )


@router.get("/operator/reports/account-hourly", response_model=schemas.AccountHourlyReportList)
def list_account_hourly_reports(
    account_id: int | None = Query(default=None),
    report_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> schemas.AccountHourlyReportList:
    items = service.list_account_hourly_reports(db, account_id=account_id, report_date=report_date)
    return schemas.AccountHourlyReportList(
        timezone=service.resolve_report_timezone(
            db,
            account_id=account_id,
            account_ids={item.account_id for item in items},
        ),
        items=items,
    )


@router.get("/operator/reports/site-daily", response_model=schemas.SiteDailyReportList)
def list_site_daily_reports(
    account_id: int | None = Query(default=None),
    report_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> schemas.SiteDailyReportList:
    items = service.list_site_daily_reports(db, account_id=account_id, report_date=report_date)
    return schemas.SiteDailyReportList(
        timezone=service.resolve_report_timezone(
            db,
            account_id=account_id,
            account_ids={item.account_id for item in items},
        ),
        coverage=service.build_hourly_coverage(db, account_id=account_id, report_date=report_date),
        items=items,
    )


@router.get("/operator/reports/site-hourly", response_model=schemas.SiteHourlyReportList)
def list_site_hourly_reports(
    account_id: int | None = Query(default=None),
    report_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> schemas.SiteHourlyReportList:
    items = service.list_site_hourly_reports(db, account_id=account_id, report_date=report_date)
    return schemas.SiteHourlyReportList(
        timezone=service.resolve_report_timezone(
            db,
            account_id=account_id,
            account_ids={item.account_id for item in items},
        ),
        items=items,
    )


@router.get("/operator/mid-platform/resources/links", response_model=schemas.MidPlatformLinkResourceListResponse)
def list_mid_platform_link_resources(
    account_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> schemas.MidPlatformLinkResourceListResponse:
    return schemas.MidPlatformLinkResourceListResponse(
        items=service.list_mid_platform_link_resources(db, account_id=account_id)
    )


@router.get("/operator/mid-platform/resources/accounts", response_model=schemas.MidPlatformAccountResourceListResponse)
def list_mid_platform_account_resources(
    account_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> schemas.MidPlatformAccountResourceListResponse:
    return schemas.MidPlatformAccountResourceListResponse(
        items=service.list_mid_platform_account_resources(db, account_id=account_id)
    )


@router.get("/operator/mid-platform/resources/nodes", response_model=schemas.MidPlatformNodeResourceListResponse)
def list_mid_platform_node_resources(
    account_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> schemas.MidPlatformNodeResourceListResponse:
    return schemas.MidPlatformNodeResourceListResponse(
        items=service.list_mid_platform_node_resources(db, account_id=account_id)
    )


@router.get("/operator/mid-platform/resources/sites", response_model=schemas.MidPlatformSiteResourceListResponse)
def list_mid_platform_site_resources(
    account_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> schemas.MidPlatformSiteResourceListResponse:
    return schemas.MidPlatformSiteResourceListResponse(
        items=service.list_mid_platform_site_resources(db, account_id=account_id)
    )


@router.get("/operator/mid-platform/reports/site-daily", response_model=schemas.MidPlatformSiteDailyReportResponse)
def list_mid_platform_site_daily_report(
    report_date: date = Query(...),
    account_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> schemas.MidPlatformSiteDailyReportResponse:
    return service.list_mid_platform_site_daily_report(
        db,
        account_id=account_id,
        report_date=report_date,
    )


@router.get("/operator/mid-platform/reports/link-daily", response_model=schemas.MidPlatformLinkDailyReportResponse)
def list_mid_platform_link_daily_report(
    report_date: date = Query(...),
    account_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> schemas.MidPlatformLinkDailyReportResponse:
    return service.list_mid_platform_link_daily_report(
        db,
        account_id=account_id,
        report_date=report_date,
    )


@router.get("/operator/mid-platform/reports/account-daily", response_model=schemas.MidPlatformAccountDailyReportResponse)
def list_mid_platform_account_daily_report(
    report_date: date = Query(...),
    account_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> schemas.MidPlatformAccountDailyReportResponse:
    return service.list_mid_platform_account_daily_report(
        db,
        account_id=account_id,
        report_date=report_date,
    )


@router.get("/operator/mid-platform/reports/account-daily-dimensions", response_model=schemas.DimensionReportResponse)
def list_mid_platform_account_daily_dimensions(report_date: date | None = Query(default=None), start_date: date | None = Query(default=None), end_date: date | None = Query(default=None), account_id: int | None = Query(default=None), ad_country_code: str | None = Query(default=None), ad_slot_id: str | None = Query(default=None), page: int = Query(default=1, ge=1), page_size: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db)) -> schemas.DimensionReportResponse:
    return service.list_mid_platform_account_daily_dimensions(db, account_id=account_id, report_date=report_date, start_date=start_date, end_date=end_date, ad_country_code=ad_country_code, ad_slot_id=ad_slot_id, page=page, page_size=page_size)


@router.get("/operator/mid-platform/reports/site-daily-dimensions", response_model=schemas.DimensionReportResponse)
def list_mid_platform_site_daily_dimensions(report_date: date | None = Query(default=None), start_date: date | None = Query(default=None), end_date: date | None = Query(default=None), account_id: int | None = Query(default=None), site_name: str | None = Query(default=None), ad_country_code: str | None = Query(default=None), ad_slot_id: str | None = Query(default=None), page: int = Query(default=1, ge=1), page_size: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db)) -> schemas.DimensionReportResponse:
    return service.list_mid_platform_site_daily_dimensions(db, account_id=account_id, report_date=report_date, start_date=start_date, end_date=end_date, site_name=site_name, ad_country_code=ad_country_code, ad_slot_id=ad_slot_id, page=page, page_size=page_size)


@router.get("/operator/mid-platform/reports/account-hourly-dimensions", response_model=schemas.DimensionReportResponse)
def list_mid_platform_account_hourly_dimensions(report_date: date | None = Query(default=None), start_date: date | None = Query(default=None), end_date: date | None = Query(default=None), account_id: int | None = Query(default=None), ad_country_code: str | None = Query(default=None), ad_slot_id: str | None = Query(default=None), page: int = Query(default=1, ge=1), page_size: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db)) -> schemas.DimensionReportResponse:
    return service.list_mid_platform_account_hourly_dimensions(db, account_id=account_id, report_date=report_date, start_date=start_date, end_date=end_date, ad_country_code=ad_country_code, ad_slot_id=ad_slot_id, page=page, page_size=page_size)


@router.get("/operator/mid-platform/reports/site-hourly-dimensions", response_model=schemas.DimensionReportResponse)
def list_mid_platform_site_hourly_dimensions(report_date: date | None = Query(default=None), start_date: date | None = Query(default=None), end_date: date | None = Query(default=None), account_id: int | None = Query(default=None), site_name: str | None = Query(default=None), ad_country_code: str | None = Query(default=None), ad_slot_id: str | None = Query(default=None), page: int = Query(default=1, ge=1), page_size: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db)) -> schemas.DimensionReportResponse:
    return service.list_mid_platform_site_hourly_dimensions(db, account_id=account_id, report_date=report_date, start_date=start_date, end_date=end_date, site_name=site_name, ad_country_code=ad_country_code, ad_slot_id=ad_slot_id, page=page, page_size=page_size)


@router.get("/operator/mid-platform/reports/account-hourly", response_model=schemas.MidPlatformAccountHourlyReportResponse)
def list_mid_platform_account_hourly_report(
    report_date: date = Query(...),
    account_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> schemas.MidPlatformAccountHourlyReportResponse:
    return service.list_mid_platform_account_hourly_report(db, account_id=account_id, report_date=report_date)


@router.get("/operator/mid-platform/reports/site-hourly", response_model=schemas.MidPlatformSiteHourlyReportResponse)
def list_mid_platform_site_hourly_report(
    report_date: date = Query(...),
    account_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> schemas.MidPlatformSiteHourlyReportResponse:
    return service.list_mid_platform_site_hourly_report(db, account_id=account_id, report_date=report_date)


@router.get("/oauth/google/callback", response_model=schemas.OAuthCallbackResponse)
def google_oauth_callback(
    state: str = Query(...),
    code: str = Query(...),
    iss: str = Query(...),
    db: Session = Depends(get_db),
) -> schemas.OAuthCallbackResponse:
    try:
        return oauth_service.handle_google_callback(db, state=state, code=code, issuer=iss)
    except oauth_service.OAuthStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth authorization state is invalid or expired",
        ) from exc


@router.post("/collector/heartbeat", response_model=schemas.HeartbeatResponse)
def collector_heartbeat(
    payload: schemas.HeartbeatRequest,
    db: Session = Depends(get_db),
    instance: CollectorInstance = Depends(get_authenticated_instance),
) -> schemas.HeartbeatResponse:
    updated_instance, observed_egress_ip = service.record_heartbeat(db, instance, payload)
    return schemas.HeartbeatResponse(
        instance_id=updated_instance.id,
        status=updated_instance.status,
        last_heartbeat_at=updated_instance.last_heartbeat_at,
        observed_egress_ip=observed_egress_ip,
    )


@router.get("/collector/runtime-config", response_model=schemas.CollectorRuntimeConfigResponse)
def get_collector_runtime_config(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    instance: CollectorInstance = Depends(get_authenticated_instance),
) -> schemas.CollectorRuntimeConfigResponse:
    settings = get_settings()
    response.headers["Cache-Control"] = "no-store"
    return service.build_runtime_config(
        db,
        instance,
        control_plane_base_url=str(request.base_url).rstrip("/"),
        egress_check_url=settings.collector_egress_check_url,
        allow_stub_runtime_with_managed_credentials=settings.allow_stub_runtime_with_managed_credentials,
    )


@router.post("/collector/oauth/credential-ack", response_model=schemas.OAuthCredentialAckResponse)
def acknowledge_oauth_credential(
    payload: schemas.OAuthCredentialAckRequest,
    db: Session = Depends(get_db),
    instance: CollectorInstance = Depends(get_authenticated_instance),
) -> schemas.OAuthCredentialAckResponse:
    return oauth_service.acknowledge_credential_validation(db, instance=instance, payload=payload)


@router.get("/collector/tasks/next", response_model=schemas.SyncTaskRead)
def get_next_task(
    credential_version: int | None = Query(default=None),
    db: Session = Depends(get_db),
    instance: CollectorInstance = Depends(get_authenticated_instance),
) -> schemas.SyncTaskRead | Response:
    task = service.claim_next_task(db, instance, credential_version=credential_version)
    if task is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return task


@router.post("/collector/tasks/{task_id}/status", response_model=schemas.SyncTaskRead)
def update_task_status(
    task_id: int,
    payload: schemas.TaskStatusUpdate,
    db: Session = Depends(get_db),
    instance: CollectorInstance = Depends(get_authenticated_instance),
) -> schemas.SyncTaskRead:
    return service.update_task_status(db, instance, task_id, payload)


@router.post(
    "/collector/tasks/{task_id}/batches",
    response_model=schemas.BatchIngestionResponse,
    status_code=status.HTTP_201_CREATED,
)
def ingest_task_batch(
    task_id: int,
    payload: schemas.BatchIngestionRequest,
    response: Response,
    db: Session = Depends(get_db),
    instance: CollectorInstance = Depends(get_authenticated_instance),
) -> schemas.BatchIngestionResponse:
    batch, duplicate = ingestion_service.ingest_batch(db, instance, task_id, payload)
    if duplicate:
        response.status_code = status.HTTP_200_OK
    return schemas.BatchIngestionResponse.model_validate(batch).model_copy(update={"duplicate": duplicate})
