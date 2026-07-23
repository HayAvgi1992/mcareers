"""Executor loop: pop Redis → claim DB → run handler → finalize."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from app.config import settings
from app.db.models import Job, JobStatus
from app.db.session import SessionLocal
from app.jobs.base import HandlerError, UnknownJobTypeError
from app.jobs.registry import get_handler
from app.queue.client import QueueClient
from app.worker.claim import claim_job

logger = logging.getLogger(__name__)


def _safe_error_message(exc: BaseException) -> str:
    """Store a short error for API clients — no stack traces / paths."""
    msg = str(exc).strip() or type(exc).__name__
    return msg[:1000]


async def _complete_job(session, job: Job, result: dict[str, Any]) -> None:
    job.status = JobStatus.completed
    job.result = result
    job.progress_pct = 100
    job.completed_at = datetime.now(UTC)
    job.error_message = None
    job.leased_until = None
    await session.commit()


async def _fail_job(session, job: Job, error_message: str) -> None:
    """Mark permanently failed (retry/backoff lands in Story 2.2)."""
    job.status = JobStatus.failed
    job.error_message = error_message
    job.completed_at = datetime.now(UTC)
    job.leased_until = None
    await session.commit()


async def process_one(queue: QueueClient, worker_id: str) -> bool:
    """
    Process a single job from the queue.
    Returns True if a Redis entry was consumed (even if claim skipped);
    False if the queue was empty.
    """
    job_id = await queue.dequeue()
    if job_id is None:
        return False

    async with SessionLocal() as session:
        job = await claim_job(
            session,
            job_id,
            worker_id=worker_id,
            lease_seconds=settings.worker_lease_seconds,
        )
        if job is None:
            logger.debug("job_claim_skipped job_id=%s", job_id)
            return True

        logger.info(
            "job_claimed job_id=%s job_type=%s status=%s",
            job.id,
            job.job_type.value,
            job.status.value,
        )
        logger.info(
            "job_started job_id=%s job_type=%s status=%s",
            job.id,
            job.job_type.value,
            job.status.value,
        )

        try:
            handler = get_handler(job.job_type)
            result = await handler.run(job)
            await _complete_job(session, job, result)
            logger.info(
                "job_completed job_id=%s job_type=%s status=%s",
                job.id,
                job.job_type.value,
                JobStatus.completed.value,
            )
        except (HandlerError, UnknownJobTypeError) as exc:
            await _fail_job(session, job, _safe_error_message(exc))
            logger.warning(
                "job_failed job_id=%s job_type=%s error_message=%s",
                job.id,
                job.job_type.value,
                _safe_error_message(exc),
            )
        except Exception as exc:
            await _fail_job(session, job, _safe_error_message(exc))
            logger.exception(
                "job_failed job_id=%s job_type=%s error_message=%s",
                job.id,
                job.job_type.value,
                _safe_error_message(exc),
            )

    return True


async def run_executor_loop(queue: QueueClient, worker_id: str) -> None:
    """Continuously drain the pending queue until cancelled."""
    logger.info("executor_started worker_id=%s", worker_id)
    while True:
        processed = await process_one(queue, worker_id)
        if not processed:
            await asyncio.sleep(settings.executor_poll_interval_seconds)
