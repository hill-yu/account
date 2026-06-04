from __future__ import annotations

from datetime import date
from typing import Protocol

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.vps_database import get_session_factory
from app.vps_service import AccountConfigError, FetchExecutionError, VpsFetchService


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


class FetchService(Protocol):
    def run_fetch(
        self,
        *,
        account_key: str,
        report_date: date,
        trigger_source: str,
        request_id: str,
    ):
        ...


def create_app(*, fetch_service: FetchService | None = None) -> FastAPI:
    application = FastAPI(title="ADX VPS Fetch API")
    service = fetch_service if fetch_service is not None else VpsFetchService(session_factory=get_session_factory())

    @application.get("/health")
    def healthcheck() -> dict[str, str]:
        return {"status": "ok"}

    @application.post("/internal/fetch", response_model=FetchResponse)
    def internal_fetch(payload: FetchRequest) -> FetchResponse:
        try:
            result = service.run_fetch(
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

    return application


app = create_app()


def _status_code_for_fetch_error(error: FetchExecutionError) -> int:
    message = str(error).lower()
    if "already executing" in message or "already running" in message:
        return 409
    return 502
