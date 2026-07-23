"""Job business logic for the API (submit, get, list, cancel, retry)."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import JobCreate
from app.config import settings
from app.db.models import Job, JobStatus
from app.queue.client import QueueClient
from app.queue.keys import priority_score

logger = logging.getLogger(__name__)


async def submit_job(
    session: AsyncSession,
    queue: QueueClient,
    data: JobCreate,
) -> Job:
    """Persist a pending job, then enqueue to Redis for dispatch."""
    job = Job(
        job_type=data.job_type,
        payload=data.payload,
        priority=data.priority,
        status=JobStatus.pending,
        max_attempts=settings.default_max_attempts,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    logger.info(
        "job_submitted job_id=%s job_type=%s status=%s",
        job.id,
        job.job_type.value,
        job.status.value,
    )

    # Postgres committed first; Redis is dispatch-only (feeder can recover later).
    await queue.enqueue(job.id, priority_score(job.priority, job.created_at))
    logger.info(
        "job_enqueued job_id=%s job_type=%s status=%s",
        job.id,
        job.job_type.value,
        job.status.value,
    )
    return job


async def get_job(session: AsyncSession, job_id: UUID) -> Job | None:
    return await session.scalar(select(Job).where(Job.id == job_id))
