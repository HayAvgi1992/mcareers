"""Dead letter queue — permanently failed jobs indexed in Redis for inspection."""

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
from app.queue.keys import JOBS_DEAD_LETTER
from app.worker.executor import process_one
from app.worker.feeder import promote_ready_jobs

pytestmark = pytest.mark.usefixtures("clean_jobs")


@pytest.mark.asyncio
@patch("app.jobs.webhook.asyncio.sleep", new_callable=AsyncMock)
@patch(
    "app.jobs.webhook.run",
    new_callable=AsyncMock,
    side_effect=HandlerError("webhook delivery failed"),
)
async def test_permanent_failure_pushes_dead_letter(
    _run: AsyncMock,
    _sleep: AsyncMock,
    client: AsyncClient,
    queue,
    redis_client: Redis,
) -> None:
    created = await client.post(
        "/jobs",
        json={"job_type": "webhook", "payload": {"url": "https://example.com"}},
    )
    job_id = uuid.UUID(created.json()["id"])

    for _ in range(3):
        async with SessionLocal() as session:
            job = await session.scalar(select(Job).where(Job.id == job_id))
            assert job is not None
            job.status = JobStatus.pending
            job.next_run_at = None
            await session.commit()
        await promote_ready_jobs(queue)
        assert await process_one(queue, worker_id="dlq-worker") is True

    async with SessionLocal() as session:
        job = await session.scalar(select(Job).where(Job.id == job_id))
        assert job is not None
        assert job.status == JobStatus.failed

    members = await redis_client.lrange(JOBS_DEAD_LETTER, 0, -1)
    assert str(job_id) in members


@pytest.mark.asyncio
@patch("app.jobs.webhook.asyncio.sleep", new_callable=AsyncMock)
@patch(
    "app.jobs.webhook.run",
    new_callable=AsyncMock,
    side_effect=HandlerError("transient"),
)
async def test_retryable_failure_does_not_dead_letter(
    _run: AsyncMock,
    _sleep: AsyncMock,
    client: AsyncClient,
    queue,
    redis_client: Redis,
) -> None:
    created = await client.post(
        "/jobs",
        json={"job_type": "webhook", "payload": {"url": "https://example.com"}},
    )
    job_id = uuid.UUID(created.json()["id"])

    assert await process_one(queue, worker_id="dlq-worker") is True

    async with SessionLocal() as session:
        job = await session.scalar(select(Job).where(Job.id == job_id))
        assert job is not None
        assert job.status == JobStatus.pending

    assert await redis_client.llen(JOBS_DEAD_LETTER) == 0


@pytest.mark.asyncio
async def test_manual_retry_removes_from_dead_letter(
    client: AsyncClient,
    redis_client: Redis,
) -> None:
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

    await redis_client.lpush(JOBS_DEAD_LETTER, str(job_id))
    assert await redis_client.llen(JOBS_DEAD_LETTER) == 1

    response = await client.post(f"/jobs/{job_id}/retry")
    assert response.status_code == 200
    assert response.json()["status"] == "pending"
    assert await redis_client.llen(JOBS_DEAD_LETTER) == 0


@pytest.mark.asyncio
async def test_health_includes_dead_letter_depth(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["queue"]["dead_letter_depth"] == 0
