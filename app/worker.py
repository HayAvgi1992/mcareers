"""Worker process entrypoint (feeder + executor loops land in later stories)."""

from __future__ import annotations

import asyncio
import logging

from app.db.session import check_db, dispose_engine
from app.queue.client import QueueClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


async def run() -> None:
    await check_db()
    queue = await QueueClient.connect()
    logger.info("worker_connected", extra={"db": True, "redis": True})
    try:
        # Placeholder idle loop until Stories 1.4 / 1.5 wire executor + feeder.
        while True:
            await asyncio.sleep(60)
    finally:
        await queue.close()
        await dispose_engine()
        logger.info("worker_shutdown")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
