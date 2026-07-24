"""Reaper: recover jobs stuck in processing after lease expiry."""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import func, select, update

from app.config import settings
from app.db.models import Job, JobStatus
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

_REAPER_BATCH_SIZE = 100


async def reap_expired_leases(*, limit: int = _REAPER_BATCH_SIZE) -> int:
    """
    Reset processing jobs whose lease has expired back to pending.
    Feeder re-enqueues them — reaper does not touch Redis.
    Returns how many jobs were reaped this cycle.
    """
    async with SessionLocal() as session:
        expired_ids = list(
            await session.scalars(
                select(Job.id)
                .where(
                    Job.status == JobStatus.processing,
                    Job.leased_until.is_not(None),
                    Job.leased_until < func.now(),
                )
                .order_by(Job.leased_until.asc())
                .limit(limit)
            )
        )

        reaped = 0
        for job_id in expired_ids:
            result = await session.execute(
                update(Job)
                .where(
                    Job.id == job_id,
                    Job.status == JobStatus.processing,
                    Job.leased_until.is_not(None),
                    Job.leased_until < func.now(),
                )
                .values(
                    status=JobStatus.pending,
                    worker_id=None,
                    leased_until=None,
                    next_run_at=None,
                )
                .returning(Job)
            )
            job = result.scalar_one_or_none()
            if job is None:
                await session.rollback()
                continue
            await session.commit()
            reaped += 1
            logger.info(
                "job_reaped job_id=%s job_type=%s status=%s attempt_count=%s",
                job.id,
                job.job_type.value,
                JobStatus.pending.value,
                job.attempt_count,
            )

    return reaped


async def run_reaper_loop() -> None:
    """Periodically reclaim jobs with expired processing leases."""
    logger.info("reaper_started")
    while True:
        await reap_expired_leases()
        await asyncio.sleep(settings.reaper_poll_interval_seconds)
