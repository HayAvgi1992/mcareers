"""Worker process entrypoint (feeder + executor loops land in later stories)."""

from __future__ import annotations

import asyncio
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


async def run() -> None:
    logger.info("worker_started")
    # Placeholder idle loop until Stories 1.4 / 1.5 wire executor + feeder.
    while True:
        await asyncio.sleep(60)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
