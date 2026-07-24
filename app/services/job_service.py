"""Job business logic for the API (submit, get, list, cancel, retry)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import JobCreate
from app.config import settings
from app.db.models import Job, JobStatus
from app.queue.client import QueueClient
from app.queue.keys import priority_score
from app.services.idempotency import (
    find_job_by_idempotency_key,
    normalize_idempotency_key,
)

logger = logging.getLogger(__name__)


class JobNotFoundError(Exception):
    """No job exists for the given id."""


class JobConflictError(Exception):
    """Job exists but the requested transition is not allowed."""


async def submit_job(
    session: AsyncSession,
    queue: QueueClient,
    data: JobCreate,
    *,
    idempotency_key: str | None = None,
) -> tuple[Job, bool]:
    """
    Persist a pending job, then enqueue to Redis.
    Returns (job, created). created=False for idempotent duplicates.
    """
    key = normalize_idempotency_key(idempotency_key)
    if key is not None:
        existing = await find_job_by_idempotency_key(session, key)
        if existing is not None:
            logger.info(
                "job_submitted job_id=%s job_type=%s status=%s duplicate=true",
                existing.id,
                existing.job_type.value,
                existing.status.value,
            )
            return existing, False

    job = Job(
        job_type=data.job_type,
        payload=data.payload,
        priority=data.priority,
        status=JobStatus.pending,
        max_attempts=settings.default_max_attempts,
        idempotency_key=key,
    )
    session.add(job)
    try:
        await session.commit()
    except IntegrityError:
        # Race condition: concurrent duplicate insert on the partial unique index.
        await session.rollback() # rollback the transaction to avoid the duplicate insert
        if key is None: # if the idempotency key is not provided, raise an error (means the error is not a duplicate insert with the same idempotency key)
            raise
        existing = await find_job_by_idempotency_key(session, key)
        if existing is None: # another constraint violation occurred
            raise # raise the original error to the caller
        logger.info(
            "job_submitted job_id=%s job_type=%s status=%s duplicate=true",
            existing.id,
            existing.job_type.value,
            existing.status.value,
        )
        return existing, False # return the existing job and False to indicate that the job was not created

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
    return job, True


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
