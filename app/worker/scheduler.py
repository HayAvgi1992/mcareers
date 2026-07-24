"""Scheduler: promote due scheduled jobs → pending + Redis jobs:pending."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, update

from app.config import settings
from app.db.models import Job, JobStatus
from app.db.session import SessionLocal
from app.queue.client import QueueClient
from app.queue.keys import priority_score

logger = logging.getLogger(__name__)

_SCHEDULER_BATCH_SIZE = 100
MIN_SLEEP = 0.05


async def promote_due_scheduled(
    queue: QueueClient,
    *,
    limit: int = _SCHEDULER_BATCH_SIZE,
    now: datetime | None = None,
) -> int:
    """
    Move due scheduled jobs to pending and enqueue them.
    Uses Redis due members plus a DB scan (Postgres wins / recovery).
    Returns how many jobs were promoted this cycle.
    """
    moment = now or datetime.now(UTC)
    now_ts = moment.timestamp()
    # get the job IDs from the Redis scheduled ZSET that are due to run at or before the current time
    redis_ids = await queue.due_scheduled(now=now_ts, limit=limit)

    async with SessionLocal() as session:
        # get the job IDs from the database that are scheduled to run at or before the current time
        db_ids = list(
            await session.scalars(
                select(Job.id)
                .where(
                    Job.status == JobStatus.scheduled,
                    Job.scheduled_at <= moment,
                )
                .order_by(Job.scheduled_at.asc())
                .limit(limit)
            )
        )
        # combine the job IDs from the Redis and database - union of the two sets and remove duplicates
        candidates: list[UUID] = list(dict.fromkeys([*redis_ids, *db_ids]))
        promoted = 0

        for job_id in candidates:
            result = await session.execute(
                update(Job)
                .where(
                    Job.id == job_id,
                    Job.status == JobStatus.scheduled,
                    Job.scheduled_at <= func.now(),
                )
                .values(status=JobStatus.pending, next_run_at=None)
                .returning(Job)
            )
            job = result.scalar_one_or_none()
            if job is None:
                # rollback the transaction to avoid the update if the job is not found -job is not scheduled anymore, it was cancelled or it was not yet due or another scheduler already promoted it
                await session.rollback()
                # Cancelled or not yet due — drop stale Redis entry. DB is the source of truth.
                await queue.remove_scheduled(job_id)
                continue # continue to the next job
            # commit the transaction to update the job status to pending
            await session.commit()
            # enqueue the job to the Redis pending queue
    return promoted


async def run_scheduler_loop(queue: QueueClient) -> None:
    logger.info("scheduler_started")

    max_sleep = settings.scheduler_poll_interval_seconds

    while True:
        await promote_due_scheduled(queue)

        next_score = await queue.next_scheduled_score()

        target_sleep = (
            max_sleep
            if next_score is None
            else min(max_sleep, next_score - time.time()) # sleep for the remaining time until the next scheduled job
        )

        await asyncio.sleep(max(MIN_SLEEP, target_sleep))
