"""Scheduler: promote due scheduled jobs → pending + Redis jobs:pending."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, update

from app.config import settings
from app.db.models import Job, JobStatus
from app.db.session import SessionLocal
from app.logging_config import get_logger
from app.queue.client import QueueClient
from app.queue.keys import priority_score

logger = get_logger(__name__)

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
    redis_ids = await queue.due_scheduled(now=now_ts, limit=limit)

    async with SessionLocal() as session:
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
                await session.rollback()
                # Cancelled or not yet due — drop stale Redis entry. DB wins.
                await queue.remove_scheduled(job_id)
                continue
            await session.commit()

            await queue.remove_scheduled(job_id)
            await queue.enqueue(job.id, priority_score(job.priority, job.created_at))
            promoted += 1
            logger.info(
                "job_schedule_promoted",
                job_id=str(job.id),
                job_type=job.job_type.value,
                status=JobStatus.pending.value,
            )

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
            else min(max_sleep, next_score - time.time())
        )

        await asyncio.sleep(max(MIN_SLEEP, target_sleep))
