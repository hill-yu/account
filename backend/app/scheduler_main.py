from __future__ import annotations

import asyncio
import logging

from app.collectors.scheduler import FetchScheduler
from app.config import get_settings


async def run_scheduler() -> None:
    """Run the scheduler only in its dedicated process, never in the web ASGI app."""
    settings = get_settings()
    scheduler = FetchScheduler(timeout_seconds=settings.operator_remote_report_timeout_seconds)
    while True:
        try:
            await asyncio.to_thread(scheduler.run_pending_once)
        except Exception:  # noqa: BLE001
            logging.exception("Fetch scheduler pass failed")
        await asyncio.sleep(30)


def main() -> None:
    asyncio.run(run_scheduler())


if __name__ == "__main__":
    main()
