"""Automatic retry — DB backoff only; worker does not re-enqueue."""

from __future__ import annotations

import uuid
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

pytestmark = pytest.mark.usefixtures("clean_jobs")


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
