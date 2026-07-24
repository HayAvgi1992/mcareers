"""Tests for automatic retry with exponential backoff."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, JobStatus, JobType
from app.db.session import SessionLocal
from app.jobs.base import HandlerError
from app.queue.client import QueueClient
from app.queue.keys import JOBS_PENDING
from app.worker.executor import process_one
from app.worker.feeder import promote_ready_jobs
from app.worker.retry import apply_failure, backoff_seconds, should_retry

pytestmark = pytest.mark.usefixtures("clean_jobs")


def test_backoff_schedule() -> None:
    assert backoff_seconds(1) == 30
    assert backoff_seconds(2) == 120
    assert should_retry(1, 3) is True
    assert should_retry(2, 3) is True
    assert should_retry(3, 3) is False


@pytest.mark.asyncio
async def test_apply_failure_schedules_retry(db_session: AsyncSession) -> None:
    job = Job(
        job_type=JobType.webhook,
        payload={},
        status=JobStatus.processing,
        attempt_count=1,
        max_attempts=3,
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)

    fixed_now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    await apply_failure(db_session, job, "boom", now=fixed_now)

    assert job.status == JobStatus.pending
    assert job.next_run_at == fixed_now + timedelta(seconds=30)
    assert job.error_message == "boom"
    assert job.completed_at is None


@pytest.mark.asyncio
async def test_apply_failure_permanent_after_max_attempts(
    db_session: AsyncSession,
) -> None:
    job = Job(
        job_type=JobType.webhook,
        payload={},
        status=JobStatus.processing,
        attempt_count=3,
        max_attempts=3,
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)

    await apply_failure(db_session, job, "give up")

    assert job.status == JobStatus.failed
    assert job.next_run_at is None
    assert job.completed_at is not None
    assert job.error_message == "give up"


@pytest.mark.asyncio
@patch("app.jobs.webhook.asyncio.sleep", new_callable=AsyncMock)
@patch(
    "app.jobs.webhook.run",
    new_callable=AsyncMock,
    side_effect=HandlerError("webhook delivery failed"),
)
async def test_webhook_failure_schedules_retry_without_redis_push(
    _run: AsyncMock,
    _sleep: AsyncMock,
    client: AsyncClient,
    redis_client: Redis,
) -> None:
    created = await client.post(
        "/jobs",
        json={"job_type": "webhook", "payload": {"url": "https://example.com"}},
    )
    assert created.status_code == 201
    job_id = uuid.UUID(created.json()["id"])

    # Remove API enqueue entry after we pop via process_one; assert executor
    # does not push back on failure.
    queue = await QueueClient.connect()
    enqueue_calls_before = 0
    original_enqueue = queue.enqueue

    async def counting_enqueue(*args, **kwargs):
        nonlocal enqueue_calls_before
        enqueue_calls_before += 1
        return await original_enqueue(*args, **kwargs)

    queue.enqueue = counting_enqueue  # type: ignore[method-assign]
    try:
        assert await process_one(queue, worker_id="retry-worker") is True
        assert enqueue_calls_before == 0
    finally:
        await queue.close()

    async with SessionLocal() as session:
        job = await session.scalar(select(Job).where(Job.id == job_id))
        assert job is not None
        assert job.status == JobStatus.pending
        assert job.attempt_count == 1
        assert job.next_run_at is not None
        assert job.error_message == "webhook delivery failed"

    # Not re-queued by the worker (may still be absent until feeder when due).
    assert await redis_client.zscore(JOBS_PENDING, str(job_id)) is None


@pytest.mark.asyncio
@patch("app.jobs.webhook.asyncio.sleep", new_callable=AsyncMock)
@patch(
    "app.jobs.webhook.run",
    new_callable=AsyncMock,
    side_effect=HandlerError("webhook delivery failed"),
)
async def test_after_three_failures_job_is_permanently_failed(
    _run: AsyncMock,
    _sleep: AsyncMock,
    client: AsyncClient,
) -> None:
    created = await client.post(
        "/jobs",
        json={"job_type": "webhook", "payload": {"url": "https://example.com"}},
    )
    job_id = uuid.UUID(created.json()["id"])

    queue = await QueueClient.connect()
    try:
        for _ in range(3):
            # Make the job due and present in Redis for each attempt.
            async with SessionLocal() as session:
                job = await session.scalar(select(Job).where(Job.id == job_id))
                assert job is not None
                job.status = JobStatus.pending
                job.next_run_at = None
                await session.commit()
            await promote_ready_jobs(queue)
            assert await process_one(queue, worker_id="retry-worker") is True
    finally:
        await queue.close()

    async with SessionLocal() as session:
        job = await session.scalar(select(Job).where(Job.id == job_id))
        assert job is not None
        assert job.status == JobStatus.failed
        assert job.attempt_count == 3
        assert job.next_run_at is None


@pytest.mark.asyncio
async def test_feeder_promotes_retry_when_next_run_at_due(
    client: AsyncClient,
    redis_client: Redis,
) -> None:
    created = await client.post(
        "/jobs",
        json={"job_type": "email", "payload": {"to": "a@example.com"}},
    )
    job_id = uuid.UUID(created.json()["id"])
    # Clear API enqueue; simulate a scheduled retry that is now due.
    await redis_client.delete(JOBS_PENDING)

    async with SessionLocal() as session:
        job = await session.scalar(select(Job).where(Job.id == job_id))
        assert job is not None
        job.status = JobStatus.pending
        job.attempt_count = 1
        job.next_run_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()

    queue = await QueueClient.connect()
    try:
        promoted = await promote_ready_jobs(queue)
    finally:
        await queue.close()

    assert promoted == 1
    assert await redis_client.zscore(JOBS_PENDING, str(job_id)) is not None
