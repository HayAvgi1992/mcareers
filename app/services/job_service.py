"""Job business logic for the API (submit, get, list, cancel, retry)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import JobCreate
from app.config import settings
from app.db.models import Job, JobStatus
from app.queue.client import QueueClient
from app.queue.keys import priority_score

logger = logging.getLogger(__name__)


class JobNotFoundError(Exception):
    """No job exists for the given id."""


class JobConflictError(Exception):
    """Job exists but the requested transition is not allowed."""


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


async def cancel_job(
    session: AsyncSession,
    queue: QueueClient,
    job_id: UUID,
) -> Job:
    """
    Cancel a pending job. Postgres is updated first; Redis ZREM is best-effort
    cleanup (stale pops still fail the DB claim).
    """
    job = await get_job(session, job_id)
    if job is None:
        raise JobNotFoundError(f"job {job_id} not found")
    if job.status != JobStatus.pending:
        raise JobConflictError(
            f"only pending jobs can be cancelled (status={job.status.value})"
        )

    job.status = JobStatus.cancelled
    job.next_run_at = None
    job.leased_until = None
    job.worker_id = None
    await session.commit()
    await session.refresh(job)

    await queue.remove(job_id)

    logger.info(
        "job_cancelled job_id=%s job_type=%s status=%s",
        job.id,
        job.job_type.value,
        job.status.value,
    )
    return job


async def manual_retry(session: AsyncSession, job_id: UUID) -> Job:
    """
    Re-open a permanently failed job for one more attempt.
    Feeder enqueues when next_run_at is due — API does not push Redis.
    """
    job = await get_job(session, job_id)
    if job is None:
        raise JobNotFoundError(f"job {job_id} not found")
    if job.status != JobStatus.failed:
        raise JobConflictError(
            f"only failed jobs can be retried (status={job.status.value})"
        )

    job.max_attempts += 1
    job.status = JobStatus.pending
    job.next_run_at = datetime.now(UTC)
    job.completed_at = None
    job.started_at = None
    job.leased_until = None
    job.worker_id = None
    job.error_message = None
    await session.commit()
    await session.refresh(job)

    logger.info(
        "job_manual_retry job_id=%s job_type=%s status=%s max_attempts=%s",
        job.id,
        job.job_type.value,
        job.status.value,
        job.max_attempts,
    )
    return job
