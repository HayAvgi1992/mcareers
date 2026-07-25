"""Dead letter — permanent failure indexes job id in Redis DLQ."""

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
