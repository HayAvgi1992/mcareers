"""Worker liveness: Redis /health beats + DB lease renewal while processing."""

from __future__ import annotations

import asyncio
import uuid

from app.config import settings
from app.logging_config import get_logger
from app.queue.client import QueueClient
from app.worker.claim import renew_job_lease
from app.worker.lifecycle import wait_or_stop

logger = get_logger(__name__)


class LeaseHolder:
    """Shared between executor and heartbeat: job currently held by this worker."""

    def __init__(self) -> None:
        self.job_id: uuid.UUID | None = None


async def run_heartbeat_loop(
    queue: QueueClient,
    worker_id: str,
    stop: asyncio.Event,
    lease_holder: LeaseHolder,
) -> None:
    """
    Periodically:
    1) refresh Redis workers:heartbeat (/health alive list)
    2) if holding a job, extend Postgres leased_until so the reaper does not
       reclaim work from a live worker
    """
    logger.info("heartbeat_started", worker_id=worker_id)
    try:
        while not stop.is_set():
            await queue.worker_heartbeat(worker_id)
            job_id = lease_holder.job_id
            if job_id is not None:
                renewed = await renew_job_lease(
                    job_id,
                    worker_id,
                    settings.worker_lease_seconds,
                )
                if renewed is not None:
                    logger.debug(
                        "lease_renewed",
                        job_id=str(job_id),
                        worker_id=worker_id,
                        leased_until=renewed.isoformat(),
                    )
                else:
                    # Job finished, failed, or was reaped — clear stale holder.
                    if lease_holder.job_id == job_id:
                        lease_holder.job_id = None
                    logger.warning(
                        "lease_renew_skipped",
                        job_id=str(job_id),
                        worker_id=worker_id,
                    )
            await wait_or_stop(stop, settings.worker_heartbeat_interval_seconds)
    finally:
        await queue.worker_offline(worker_id)
        logger.info("heartbeat_stopped", worker_id=worker_id)
