"""DB feeder: promote ready pending jobs into Redis jobs:pending."""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import func, or_, select

from app.config import settings
from app.db.models import Job, JobStatus
from app.db.session import SessionLocal
from app.queue.client import QueueClient
from app.queue.keys import priority_score

logger = logging.getLogger(__name__)

# Cap each cycle so a large backlog doesn't stall the event loop.
_FEEDER_BATCH_SIZE = 100


async def promote_ready_jobs(
    queue: QueueClient,
    *,
    limit: int = _FEEDER_BATCH_SIZE,
) -> int:
    """
    Find DB-ready pending jobs and ZADD them to Redis (NX).
    Returns how many new Redis entries were added this cycle.
    """
    async with SessionLocal() as session:
        stmt = (
            select(Job)
            .where(
                Job.status == JobStatus.pending,
                or_(Job.next_run_at.is_(None), Job.next_run_at <= func.now()),
            )
            .order_by(Job.priority.desc(), Job.created_at.asc())
            .limit(limit)
        )
        jobs = list(await session.scalars(stmt))

    promoted = 0
    for job in jobs:
        score = priority_score(job.priority, job.created_at)
        added = await queue.enqueue(job.id, score, nx=True)
        if added:
            promoted += 1
            logger.debug(
                "job_feeder_promoted job_id=%s job_type=%s status=%s",
                job.id,
                job.job_type.value,
                job.status.value,
            )
    return promoted


async def run_feeder_loop(queue: QueueClient) -> None:
    """Periodically promote ready DB jobs into Redis."""
    logger.info("feeder_started")
    while True:
        await promote_ready_jobs(queue)
        await asyncio.sleep(settings.scheduler_poll_interval_seconds)
