"""Retry scheduling: DB-only backoff (worker never re-enqueues to Redis)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, JobStatus

logger = logging.getLogger(__name__)

# After attempt N fails, wait this many seconds before attempt N+1.
# Attempt 1 is immediate on submit (next_run_at NULL) — DECISIONS.md §4.
_BACKOFF_SECONDS_AFTER_ATTEMPT = {
    1: 30,
    2: 120,
}


def backoff_seconds(attempt_count: int) -> int:
    """Seconds to wait after a failed attempt before the next run."""
    return _BACKOFF_SECONDS_AFTER_ATTEMPT.get(attempt_count, 120)


def should_retry(attempt_count: int, max_attempts: int) -> bool:
    return attempt_count < max_attempts


async def apply_failure(
    session: AsyncSession,
    job: Job,
    error_message: str,
    *,
    now: datetime | None = None,
    permanent: bool = False,
) -> None:
    """
    Record a handler failure. Either schedule a DB-driven retry (pending +
    next_run_at) or mark permanently failed. Does not touch Redis.
    """
    now = now or datetime.now(UTC)
    job.error_message = error_message
    job.leased_until = None
    job.worker_id = None
    job.result = None
    # if not permanent and should_retry(job.attempt_count, job.max_attempts):
    if not permanent and should_retry(job.attempt_count, job.max_attempts):
        delay = backoff_seconds(job.attempt_count)
        job.status = JobStatus.pending
        job.next_run_at = now + timedelta(seconds=delay)
        job.started_at = None
        job.completed_at = None
        await session.commit()
        logger.info(
            "job_retry_scheduled job_id=%s job_type=%s status=%s "
            "attempt_count=%s next_run_at=%s",
            job.id,
            job.job_type.value,
            job.status.value,
            job.attempt_count,
            job.next_run_at.isoformat(),
        )
        return

    job.status = JobStatus.failed
    job.next_run_at = None
    job.completed_at = now
    await session.commit()
    logger.warning(
        "job_failed job_id=%s job_type=%s status=%s attempt_count=%s "
        "error_message=%s",
        job.id,
        job.job_type.value,
        job.status.value,
        job.attempt_count,
        error_message,
    )
