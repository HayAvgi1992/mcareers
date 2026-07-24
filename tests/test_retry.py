"""Automatic retry — backoff, no Redis push on failure, permanent fail."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import select

from app.db.models import Job, JobStatus
from app.db.session import SessionLocal
from app.jobs.base import HandlerError
from app.queue.client import QueueClient
from app.queue.keys import JOBS_PENDING
from app.worker.executor import process_one
from app.worker.feeder import promote_ready_jobs
from app.worker.retry import backoff_seconds, should_retry

pytestmark = pytest.mark.usefixtures("clean_jobs")


def test_backoff_schedule() -> None:
    assert backoff_seconds(1) == 30
    assert backoff_seconds(2) == 120
    assert should_retry(1, 3) is True
    assert should_retry(3, 3) is False


@pytest.mark.asyncio
@patch("app.jobs.webhook.asyncio.sleep", new_callable=AsyncMock)
@patch(
    "app.jobs.webhook.run",
    new_callable=AsyncMock,
    side_effect=HandlerError("webhook delivery failed"),
)
async def test_failure_schedules_retry_without_redis_push(
    _run: AsyncMock,
    _sleep: AsyncMock,
    client: AsyncClient,
    redis_client: Redis,
) -> None:
    created = await client.post(
        "/jobs",
        json={"job_type": "webhook", "payload": {"url": "https://example.com"}},
    )
    job_id = uuid.UUID(created.json()["id"])

    queue = await QueueClient.connect()
    try:
        assert await process_one(queue, worker_id="retry-worker") is True
    finally:
        await queue.close()

    async with SessionLocal() as session:
        job = await session.scalar(select(Job).where(Job.id == job_id))
        assert job is not None
        assert job.status == JobStatus.pending
        assert job.attempt_count == 1
        assert job.next_run_at is not None

    assert await redis_client.zscore(JOBS_PENDING, str(job_id)) is None


@pytest.mark.asyncio
@patch("app.jobs.webhook.asyncio.sleep", new_callable=AsyncMock)
@patch(
    "app.jobs.webhook.run",
    new_callable=AsyncMock,
    side_effect=HandlerError("webhook delivery failed"),
)
async def test_after_max_attempts_job_is_permanently_failed(
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


@pytest.mark.asyncio
async def test_manual_retry_reopens_failed_job(client: AsyncClient) -> None:
    created = await client.post(
        "/jobs",
        json={"job_type": "webhook", "payload": {"url": "https://example.com"}},
    )
    job_id = uuid.UUID(created.json()["id"])

    async with SessionLocal() as session:
        job = await session.scalar(select(Job).where(Job.id == job_id))
        assert job is not None
        job.status = JobStatus.failed
        job.attempt_count = 3
        job.max_attempts = 3
        job.completed_at = datetime.now(UTC)
        job.error_message = "give up"
        await session.commit()
        old_max = job.max_attempts

    response = await client.post(f"/jobs/{job_id}/retry")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending"
    assert body["max_attempts"] == old_max + 1
    assert body["next_run_at"] is not None
