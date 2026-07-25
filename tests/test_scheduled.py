"""Scheduled jobs stay out of pending until the scheduler promotes them."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import select, update

from app.db.models import Job, JobStatus
from app.db.session import SessionLocal
from app.queue.client import QueueClient
from app.queue.keys import JOBS_PENDING, JOBS_SCHEDULED
from app.worker.scheduler import promote_due_scheduled

pytestmark = pytest.mark.usefixtures("clean_jobs")


@pytest.mark.asyncio
async def test_scheduled_job_promoted_when_due(
    client: AsyncClient,
    queue: QueueClient,
    redis_client: Redis,
) -> None:
    scheduled_at = datetime.now(UTC) + timedelta(minutes=5)
    response = await client.post(
        "/jobs",
        json={
            "job_type": "email",
            "payload": {"to": "later@example.com"},
            "scheduled_at": scheduled_at.isoformat().replace("+00:00", "Z"),
        },
    )
    assert response.status_code == 201
    body = response.json()
    job_id = uuid.UUID(body["id"])
    assert body["status"] == "scheduled"

    assert await redis_client.zscore(JOBS_SCHEDULED, str(job_id)) is not None
    assert await redis_client.zscore(JOBS_PENDING, str(job_id)) is None

    # Make the job due without sleeping (API rejects past scheduled_at on create).
    async with SessionLocal() as session:
        await session.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(scheduled_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await session.commit()

    assert await promote_due_scheduled(queue) == 1

    async with SessionLocal() as session:
        job = await session.scalar(select(Job).where(Job.id == job_id))
        assert job is not None
        assert job.status == JobStatus.pending

    assert await redis_client.zscore(JOBS_PENDING, str(job_id)) is not None
    assert await redis_client.zscore(JOBS_SCHEDULED, str(job_id)) is None
