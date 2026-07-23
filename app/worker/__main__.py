"""python -m app.worker entrypoint."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import uuid

from app.db.session import check_db, dispose_engine
from app.queue.client import QueueClient
from app.worker.executor import run_executor_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


def _make_worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"


async def run() -> None:
    await check_db()
    queue = await QueueClient.connect()
    worker_id = _make_worker_id()
    logger.info("worker_connected worker_id=%s", worker_id)
    try:
        await run_executor_loop(queue, worker_id)
    finally:
        await queue.close()
        await dispose_engine()
        logger.info("worker_shutdown worker_id=%s", worker_id)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
