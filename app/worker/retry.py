"""Retry scheduling: DB-driven backoff (worker never re-enqueues to pending)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import Job, JobStatus, LogLevel
from app.logging_config import get_logger
from app.queue.client import QueueClient
from app.services.job_log import append_job_log

logger = get_logger(__name__)


def backoff_seconds(attempt_count: int) -> float:
    """
    Seconds to wait after a failed attempt before the next run.
    Attempt 1 is immediate on submit (next_run_at NULL) — DECISIONS.md §4.
    """
    if attempt_count == 1:
        return settings.retry_backoff_after_attempt_1_seconds
    if attempt_count == 2:
        return settings.retry_backoff_after_attempt_2_seconds
    return settings.retry_backoff_after_attempt_2_seconds


def should_retry(attempt_count: int, max_attempts: int) -> bool:
    return attempt_count < max_attempts


async def apply_failure(
    session: AsyncSession,
    job: Job,
    error_message: str,
    *,
    queue: QueueClient | None = None,
    now: datetime | None = None,
    permanent: bool = False,
) -> None:
    """
    Record a handler failure. Either schedule a DB-driven retry (pending +
    next_run_at) or mark permanently failed. Does not re-enqueue to pending.
    When permanently failed and ``queue`` is provided, indexes the job in the
    Redis dead-letter list for inspection.
    """
    now = now or datetime.now(UTC)
    job.error_message = error_message
    job.leased_until = None
    job.worker_id = None
    job.result = None
    if not permanent and should_retry(job.attempt_count, job.max_attempts):
        delay = backoff_seconds(job.attempt_count)
        job.status = JobStatus.pending
        job.next_run_at = now + timedelta(seconds=delay)
        job.started_at = None
        job.completed_at = None
        await append_job_log(
            session,
            job.id,
            "retry scheduled",
            level=LogLevel.warning,
            metadata={
                "status": JobStatus.pending.value,
                "attempt_count": job.attempt_count,
                "error_message": error_message,
                "next_run_at": job.next_run_at.isoformat(),
            },
        )
        await session.commit()
        logger.info(
            "job_retry_scheduled",
            job_id=str(job.id),
            job_type=job.job_type.value,
            status=job.status.value,
            attempt_count=job.attempt_count,
            next_run_at=job.next_run_at.isoformat(),
        )
        return

    job.status = JobStatus.failed
    job.next_run_at = None
    job.completed_at = now
    await append_job_log(
        session,
        job.id,
        "job failed permanently",
        level=LogLevel.error,
        metadata={
            "status": JobStatus.failed.value,
            "attempt_count": job.attempt_count,
            "error_message": error_message,
        },
    )
    await session.commit()
    logger.warning(
        "job_failed",
        job_id=str(job.id),
        job_type=job.job_type.value,
        status=job.status.value,
        attempt_count=job.attempt_count,
        error_message=error_message,
    )
    if queue is None:
        return
    await queue.dead_letter(job.id)
    logger.info(
        "job_dead_lettered",
        job_id=str(job.id),
        job_type=job.job_type.value,
        status=job.status.value,
        attempt_count=job.attempt_count,
        error_message=error_message,
    )
