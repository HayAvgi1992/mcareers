"""Tests for POST /jobs/{id}/cancel."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import select

from app.db.models import Job, JobStatus
from app.db.session import SessionLocal
from app.queue.client import QueueClient
from app.queue.keys import JOBS_PENDING, priority_score
from app.worker.executor import process_one

pytestmark = pytest.mark.usefixtures("clean_jobs")


@pytest.mark.asyncio
async def test_cancel_pending_job(
    client: AsyncClient,
    redis_client: Redis,
) -> None:
    created = await client.post(
        "/jobs",
        json={"job_type": "email", "payload": {"to": "a@example.com"}},
    )
    job_id = created.json()["id"]
    assert await redis_client.zscore(JOBS_PENDING, job_id) is not None

    response = await client.post(f"/jobs/{job_id}/cancel")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "cancelled"
    assert await redis_client.zscore(JOBS_PENDING, job_id) is None


@pytest.mark.asyncio
@patch("app.jobs.email.asyncio.sleep", new_callable=AsyncMock)
async def test_cancel_completed_returns_409(
    _sleep: AsyncMock,
    client: AsyncClient,
) -> None:
    created = await client.post(
        "/jobs",
        json={"job_type": "email", "payload": {"to": "b@example.com"}},
    )
    job_id = created.json()["id"]

    queue = await QueueClient.connect()
    try:
        await process_one(queue, worker_id="cancel-test")
    finally:
        await queue.close()

    assert (await client.get(f"/jobs/{job_id}")).json()["status"] == "completed"
    response = await client.post(f"/jobs/{job_id}/cancel")
    assert response.status_code == 409
    assert "only pending jobs" in response.json()["detail"]


@pytest.mark.asyncio
async def test_cancel_processing_returns_409(client: AsyncClient) -> None:
    created = await client.post(
        "/jobs",
        json={"job_type": "email", "payload": {"to": "c@example.com"}},
    )
    job_id = uuid.UUID(created.json()["id"])

    async with SessionLocal() as session:
        job = await session.scalar(select(Job).where(Job.id == job_id))
        assert job is not None
        job.status = JobStatus.processing
        await session.commit()

    response = await client.post(f"/jobs/{job_id}/cancel")
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_cancel_unknown_id_returns_404(client: AsyncClient) -> None:
    response = await client.post(f"/jobs/{uuid.uuid4()}/cancel")
    assert response.status_code == 404


@pytest.mark.asyncio
@patch("app.jobs.email.asyncio.sleep", new_callable=AsyncMock)
async def test_cancelled_job_not_executed(
    _sleep: AsyncMock,
    client: AsyncClient,
) -> None:
    created = await client.post(
        "/jobs",
        json={"job_type": "email", "payload": {"to": "d@example.com"}},
    )
    job_id = uuid.UUID(created.json()["id"])

    assert (await client.post(f"/jobs/{job_id}/cancel")).status_code == 200

    # Stale Redis entry as if worker popped after cancel (or ZREM raced).
    queue = await QueueClient.connect()
    try:
        async with SessionLocal() as session:
            job = await session.scalar(select(Job).where(Job.id == job_id))
            assert job is not None
            await queue.enqueue(job.id, priority_score(job.priority, job.created_at))

        assert await process_one(queue, worker_id="cancel-test") is True
    finally:
        await queue.close()

    body = (await client.get(f"/jobs/{job_id}")).json()
    assert body["status"] == "cancelled"
    assert body["result"] is None
    _sleep.assert_not_awaited()
