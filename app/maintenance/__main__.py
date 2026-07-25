"""python -m app.maintenance entrypoint (feeder + scheduler + reaper + cleanup)."""

from __future__ import annotations

import asyncio
import signal

from app.db.session import check_db, dispose_engine
from app.logging_config import configure_logging, get_logger
from app.queue.client import QueueClient
from app.worker.feeder import run_feeder_loop
from app.worker.idempotency_cleanup import run_idempotency_cleanup_loop
from app.worker.reaper import run_reaper_loop
from app.worker.scheduler import run_scheduler_loop

configure_logging()
logger = get_logger(__name__)


async def run() -> None:
    await check_db()
    queue = await QueueClient.connect()
    stop = asyncio.Event()
    logger.info("maintenance_connected")

    loop = asyncio.get_running_loop()

    def _request_shutdown() -> None:
        if not stop.is_set():
            logger.info("shutdown_signal_received")
            stop.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _request_shutdown)

    try:
        await asyncio.gather(
            run_feeder_loop(queue, stop),
            run_scheduler_loop(queue, stop),
            run_reaper_loop(stop),
            run_idempotency_cleanup_loop(stop),
        )
    finally:
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(sig)
        await queue.close()
        await dispose_engine()
        logger.info("maintenance_shutdown")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
