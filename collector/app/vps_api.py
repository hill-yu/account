from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from datetime import date
from secrets import token_hex
from typing import Protocol

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse

from app.vps_config import get_vps_settings
from app.vps_database import get_session_factory
from app.vps_service import AccountConfigError, FetchExecutionError, VpsFetchService

logger = logging.getLogger(__name__)


class FetchRequest(BaseModel):
    account_key: str = Field(min_length=1, max_length=100)
    report_date: date
    trigger_source: str = Field(min_length=1, max_length=64)
    request_id: str = Field(min_length=1, max_length=100)


class FetchResponse(BaseModel):
    ok: bool
    run_id: int
    account_key: str
    report_date: str
    row_count: int
    status: str


class SiteDailyReportItem(BaseModel):
    site_name: str
    responses_served: int
    impressions: int
    clicks: int
    revenue: str
    ecpm: str


class SiteDailyReportResponse(BaseModel):
    ok: bool
    account_key: str
    report_date: str
    has_run: bool
    run_status: str | None
    run_id: int | None
    row_count: int
    error_message: str | None
    items: list[SiteDailyReportItem]


class NetworkTimezoneResponse(BaseModel):
    ok: bool
    account_key: str
    network_timezone: str


class FetchService(Protocol):
    def get_network_timezone(self, *, account_key: str) -> str:
        ...

    def enqueue_fetch(
        self,
        *,
        account_key: str,
        report_date: date,
        trigger_source: str,
        request_id: str,
    ):
        ...

    def get_site_daily_report(
        self,
        *,
        account_key: str,
        report_date: date,
    ):
        ...

    def process_next_pending_fetch(self):
        ...


def create_app(*, fetch_service: FetchService | None = None) -> FastAPI:
    settings = get_vps_settings()
    if fetch_service is not None:
        service = fetch_service
    else:
        service = VpsFetchService(
            session_factory=get_session_factory(),
            egress_check_url=settings.egress_check_url,
            request_timeout_seconds=settings.request_timeout_seconds,
        )

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        stop_event = threading.Event()
        worker_thread: threading.Thread | None = None

        if hasattr(service, "process_next_pending_fetch"):
            def loop() -> None:
                while not stop_event.is_set():
                    try:
                        service.process_next_pending_fetch()
                    except Exception:
                        logger.exception("background fetch worker failed while processing pending runs")
                    stop_event.wait(2.0)

            worker_thread = threading.Thread(target=loop, name="adx-vps-fetch-worker", daemon=True)
            worker_thread.start()

        try:
            yield
        finally:
            stop_event.set()
            if worker_thread is not None:
                worker_thread.join(timeout=5)

    application = FastAPI(title="ADX VPS Fetch API", lifespan=lifespan)

    @application.get("/health")
    def healthcheck() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/public/fetch.php")
    def public_fetch(
        token: str = Query(default=""),
        account_key: str = Query(default=""),
        report_date: str = Query(default=""),
    ) -> JSONResponse:
        if settings.direct_collector_only:
            return JSONResponse(
                {
                    "ok": False,
                    "error_code": "FETCH_PATH_DISABLED",
                    "message": "legacy public fetch path is disabled",
                },
                status_code=409,
            )
        request_id = _build_request_id()
        validation_error = _validate_public_request(
            expected_token=settings.trigger_token,
            token=token,
            account_key=account_key,
            report_date=report_date,
        )
        if validation_error is not None:
            body, status_code = validation_error
            if "request_id" not in body:
                body["request_id"] = request_id
            return JSONResponse(body, status_code=status_code)

        parsed_report_date = date.fromisoformat(report_date)
        try:
            result = service.enqueue_fetch(
                account_key=account_key,
                report_date=parsed_report_date,
                trigger_source="php_manual",
                request_id=request_id,
            )
        except AccountConfigError as exc:
            body, status_code = _public_error("REQUEST_ERROR", str(exc), 422, request_id=request_id)
            return JSONResponse(body, status_code=status_code)
        except FetchExecutionError as exc:
            body, status_code = _public_error(
                "FETCH_ERROR",
                str(exc),
                _status_code_for_fetch_error(exc),
                request_id=request_id,
            )
            return JSONResponse(body, status_code=status_code)

        return JSONResponse(
            {
                "ok": True,
                "run_id": result.run_id,
                "account_key": result.account_key,
                "report_date": result.report_date,
                "row_count": result.row_count,
                "status": result.status,
                "request_id": request_id,
            },
            status_code=200,
        )

    @application.get("/public/report.php")
    def public_report(
        token: str = Query(default=""),
        account_key: str = Query(default=""),
        report_date: str = Query(default=""),
    ) -> JSONResponse:
        request_id = _build_request_id()
        validation_error = _validate_public_request(
            expected_token=settings.trigger_token,
            token=token,
            account_key=account_key,
            report_date=report_date,
        )
        if validation_error is not None:
            body, status_code = validation_error
            if "request_id" not in body:
                body["request_id"] = request_id
            return JSONResponse(body, status_code=status_code)

        parsed_report_date = date.fromisoformat(report_date)
        try:
            result = service.get_site_daily_report(
                account_key=account_key,
                report_date=parsed_report_date,
            )
        except AccountConfigError as exc:
            body, status_code = _public_error("REQUEST_ERROR", str(exc), 422, request_id=request_id)
            return JSONResponse(body, status_code=status_code)

        return JSONResponse(
            {
                "ok": True,
                "account_key": result.account_key,
                "report_date": result.report_date,
                "has_run": result.has_run,
                "run_status": result.run_status,
                "run_id": result.run_id,
                "row_count": result.row_count,
                "error_message": result.error_message,
                "items": result.items,
                "request_id": request_id,
            },
            status_code=200,
        )

    @application.post("/internal/fetch", response_model=FetchResponse)
    def internal_fetch(payload: FetchRequest) -> FetchResponse:
        try:
            result = service.enqueue_fetch(
                account_key=payload.account_key,
                report_date=payload.report_date,
                trigger_source=payload.trigger_source,
                request_id=payload.request_id,
            )
        except AccountConfigError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except FetchExecutionError as exc:
            raise HTTPException(status_code=_status_code_for_fetch_error(exc), detail=str(exc)) from exc

        return FetchResponse(
            ok=True,
            run_id=result.run_id,
            account_key=result.account_key,
            report_date=result.report_date,
            row_count=result.row_count,
            status=result.status,
        )

    @application.get("/internal/network-timezone", response_model=NetworkTimezoneResponse)
    def internal_network_timezone(
        account_key: str = Query(min_length=1, max_length=100),
    ) -> NetworkTimezoneResponse:
        try:
            network_timezone = service.get_network_timezone(account_key=account_key)
        except AccountConfigError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except FetchExecutionError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return NetworkTimezoneResponse(
            ok=True,
            account_key=account_key,
            network_timezone=network_timezone,
        )

    @application.get("/internal/reports/site-daily", response_model=SiteDailyReportResponse)
    def internal_site_daily_report(
        account_key: str = Query(min_length=1, max_length=100),
        report_date: date = Query(...),
    ) -> SiteDailyReportResponse:
        try:
            result = service.get_site_daily_report(
                account_key=account_key,
                report_date=report_date,
            )
        except AccountConfigError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        return SiteDailyReportResponse(
            ok=True,
            account_key=result.account_key,
            report_date=result.report_date,
            has_run=result.has_run,
            run_status=result.run_status,
            run_id=result.run_id,
            row_count=result.row_count,
            error_message=result.error_message,
            items=[SiteDailyReportItem.model_validate(item) for item in result.items],
        )

    return application


app = create_app()


def _status_code_for_fetch_error(error: FetchExecutionError) -> int:
    message = str(error).lower()
    if "already executing" in message or "already running" in message or "already queued" in message:
        return 409
    return 502


def _build_request_id() -> str:
    return f"req_{token_hex(8)}"


def _validate_public_request(
    *,
    expected_token: str,
    token: str,
    account_key: str,
    report_date: str,
) -> tuple[dict[str, object], int] | None:
    if expected_token == "" or expected_token != token:
        return _public_error("REQUEST_ERROR", "invalid token", 401)
    if account_key == "" or report_date == "":
        return _public_error("REQUEST_ERROR", "missing account_key or report_date", 400)
    try:
        parsed_date = date.fromisoformat(report_date)
    except ValueError:
        return _public_error("REQUEST_ERROR", "report_date must be YYYY-MM-DD", 400)
    if parsed_date.isoformat() != report_date:
        return _public_error("REQUEST_ERROR", "report_date must be YYYY-MM-DD", 400)
    if len(account_key) > 100:
        return _public_error("REQUEST_ERROR", "account_key is too long", 400)
    return None


def _public_error(
    error_code: str,
    message: str,
    status_code: int,
    *,
    request_id: str | None = None,
) -> tuple[dict[str, object], int]:
    body: dict[str, object] = {
        "ok": False,
        "error_code": error_code,
        "message": message,
    }
    if request_id is not None:
        body["request_id"] = request_id
    return body, status_code
