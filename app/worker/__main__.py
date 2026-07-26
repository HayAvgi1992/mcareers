"""python -m app.worker entrypoint (executor only — scale this service)."""

from __future__ import annotations

import asyncio
import os
import signal
import socket
import uuid

from app.db.session import check_db, dispose_engine
from app.logging_config import configure_logging, get_logger
from app.queue.client import QueueClient
from app.worker.executor import run_executor_loop
from app.worker.heartbeat import LeaseHolder, run_heartbeat_loop

configure_logging()
logger = get_logger(__name__)


def _make_worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"


async def run() -> None:
    await check_db()
    queue = await QueueClient.connect()
    worker_id = _make_worker_id()
    stop = asyncio.Event()
    lease_holder = LeaseHolder()
    logger.info("worker_connected", worker_id=worker_id)

    loop = asyncio.get_running_loop() # get the current event loop

    def _request_shutdown() -> None:
        if not stop.is_set():
            logger.info("shutdown_signal_received", worker_id=worker_id)
            stop.set() # set the stop event to True

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _request_shutdown)

    try:
        await asyncio.gather(
            run_executor_loop(queue, worker_id, stop, lease_holder),
            run_heartbeat_loop(queue, worker_id, stop, lease_holder),
        )
    finally:
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(sig) # clean up the signal handler
        await queue.close()
        await dispose_engine()
        logger.info("worker_shutdown", worker_id=worker_id)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
