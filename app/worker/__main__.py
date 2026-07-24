"""python -m app.worker entrypoint."""

from __future__ import annotations

import asyncio
import os
import socket
import uuid

from app.db.session import check_db, dispose_engine
from app.logging_config import configure_logging, get_logger
from app.queue.client import QueueClient
from app.worker.executor import run_executor_loop
from app.worker.feeder import run_feeder_loop
from app.worker.reaper import run_reaper_loop
from app.worker.scheduler import run_scheduler_loop

configure_logging()
logger = get_logger(__name__)


def _make_worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"


async def run() -> None:
    await check_db()
    queue = await QueueClient.connect()
    worker_id = _make_worker_id()
    logger.info("worker_connected", worker_id=worker_id)
    try:
        await asyncio.gather(
            run_executor_loop(queue, worker_id),
            run_feeder_loop(queue),
            run_scheduler_loop(queue),
            run_reaper_loop(),
        )
    finally:
        await queue.close()
        await dispose_engine()
        logger.info("worker_shutdown", worker_id=worker_id)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
