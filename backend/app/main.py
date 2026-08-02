from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.collectors.scheduler import FetchScheduler
from app.collectors import router as collectors_router
from app.config import get_settings


logger = logging.getLogger(__name__)


def create_app(
    *,
    enable_scheduler: bool = False,
    scheduler_interval_seconds: float = 30.0,
    scheduler_factory: Callable[[], FetchScheduler] | None = None,
) -> FastAPI:
    settings = get_settings()
    if settings.app_env == "production" and not settings.operator_api_token:
        raise RuntimeError("ADX_COLLECTOR_OPERATOR_API_TOKEN is required in production")

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.scheduler_enabled = enable_scheduler
        if not enable_scheduler:
            yield
            return

        scheduler = scheduler_factory() if scheduler_factory is not None else FetchScheduler(
            timeout_seconds=settings.operator_remote_report_timeout_seconds
        )
        application.state.fetch_scheduler = scheduler

        async def scheduler_loop() -> None:
            while True:
                try:
                    await asyncio.to_thread(scheduler.run_pending_once)
                except Exception:  # noqa: BLE001
                    logger.exception("Fetch scheduler pass failed")
                await asyncio.sleep(scheduler_interval_seconds)

        task = asyncio.create_task(scheduler_loop())
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    application = FastAPI(title=settings.app_name, lifespan=lifespan)
    application.state.scheduler_enabled = enable_scheduler
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:4173",
            "http://localhost:4173",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.get("/health")
    def healthcheck() -> dict[str, str]:
        return {"status": "ok"}

    application.include_router(collectors_router)

    return application


# The ASGI module is the control plane only.  Scheduler execution must be
# started explicitly through a dedicated process so a web-service restart
# cannot enqueue production collection work unexpectedly.
app = create_app()
