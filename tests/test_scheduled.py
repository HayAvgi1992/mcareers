"""Scheduled jobs — submit, promote when due, cancel, not early."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import select

from app.db.models import Job, JobStatus
from app.db.session import SessionLocal
from app.queue.client import QueueClient
from app.queue.keys import JOBS_PENDING, JOBS_SCHEDULED
from app.worker.executor import process_one
from app.worker.scheduler import promote_due_scheduled

pytestmark = pytest.mark.usefixtures("clean_jobs")


@pytest.mark.asyncio
async def test_submit_scheduled_job_not_in_pending(
    client: AsyncClient,
    redis_client: Redis,
) -> None:
    run_at = datetime.now(UTC) + timedelta(minutes=5)
    response = await client.post(
        "/jobs",
        json={
            "job_type": "email",
            "payload": {"to": "later@example.com"},
            "scheduled_at": run_at.isoformat(),
        },
    )
    assert response.status_code == 201
    body = response.json()
    job_id = body["id"]
    assert body["status"] == "scheduled"
    assert body["scheduled_at"] is not None

    assert await redis_client.zscore(JOBS_PENDING, job_id) is None
    assert await redis_client.zscore(JOBS_SCHEDULED, job_id) is not None


@pytest.mark.asyncio
async def test_scheduler_promotes_due_job_to_pending(
    client: AsyncClient,
    redis_client: Redis,
    queue: QueueClient,
) -> None:
    run_at = datetime.now(UTC) + timedelta(seconds=30)
    created = await client.post(
        "/jobs",
        json={
            "job_type": "email",
            "payload": {"to": "due@example.com"},
            "scheduled_at": run_at.isoformat(),
        },
    )
    job_id = created.json()["id"]

    # Make the job due in DB + Redis without waiting.
    async with SessionLocal() as session:
        job = await session.scalar(select(Job).where(Job.id == job_id))
        assert job is not None
        past = datetime.now(UTC) - timedelta(seconds=1)
        job.scheduled_at = past
        job.next_run_at = past
        await session.commit()
    await redis_client.zadd(JOBS_SCHEDULED, {job_id: past.timestamp()})

    promoted = await promote_due_scheduled(queue)
    assert promoted == 1
    assert await redis_client.zscore(JOBS_SCHEDULED, job_id) is None
    assert await redis_client.zscore(JOBS_PENDING, job_id) is not None

    async with SessionLocal() as session:
        job = await session.scalar(select(Job).where(Job.id == job_id))
        assert job is not None
        assert job.status == JobStatus.pending


@pytest.mark.asyncio
@patch("app.jobs.email.asyncio.sleep", new_callable=AsyncMock)
async def test_scheduled_job_not_processed_before_due(
    _sleep: AsyncMock,
    client: AsyncClient,
    queue: QueueClient,
) -> None:
    run_at = datetime.now(UTC) + timedelta(hours=1)
    created = await client.post(
        "/jobs",
        json={
            "job_type": "email",
            "payload": {"to": "wait@example.com"},
            "scheduled_at": run_at.isoformat(),
        },
    )
    job_id = created.json()["id"]

    assert await promote_due_scheduled(queue) == 0
    assert await process_one(queue, worker_id="sched-test") is False

    body = (await client.get(f"/jobs/{job_id}")).json()
    assert body["status"] == "scheduled"
    _sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_scheduled_job(
    client: AsyncClient,
    redis_client: Redis,
) -> None:
    run_at = datetime.now(UTC) + timedelta(minutes=10)
    created = await client.post(
        "/jobs",
        json={
            "job_type": "email",
            "payload": {"to": "cancel@example.com"},
            "scheduled_at": run_at.isoformat(),
        },
    )
    job_id = created.json()["id"]
    assert await redis_client.zscore(JOBS_SCHEDULED, job_id) is not None

    response = await client.post(f"/jobs/{job_id}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert await redis_client.zscore(JOBS_SCHEDULED, job_id) is None


@pytest.mark.asyncio
async def test_submit_rejects_past_scheduled_at(client: AsyncClient) -> None:
    past = datetime.now(UTC) - timedelta(minutes=1)
    response = await client.post(
        "/jobs",
        json={
            "job_type": "email",
            "payload": {},
            "scheduled_at": past.isoformat(),
        },
    )
    assert response.status_code == 422
