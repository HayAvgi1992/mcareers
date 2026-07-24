"""Tests for POST /jobs/{id}/retry."""

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
from app.worker.feeder import promote_ready_jobs

pytestmark = pytest.mark.usefixtures("clean_jobs")


async def _force_permanently_failed(client: AsyncClient) -> uuid.UUID:
    """Submit a webhook and fail it until status=failed."""
    with (
        patch("app.jobs.webhook.asyncio.sleep", new_callable=AsyncMock),
        patch(
            "app.jobs.webhook.run",
            new_callable=AsyncMock,
            side_effect=HandlerError("webhook delivery failed"),
        ),
    ):
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
                await process_one(queue, worker_id="manual-retry-setup")
        finally:
            await queue.close()
    return job_id


@pytest.mark.asyncio
async def test_manual_retry_failed_job(client: AsyncClient) -> None:
    job_id = await _force_permanently_failed(client)

    before = (await client.get(f"/jobs/{job_id}")).json()
    assert before["status"] == "failed"
    assert before["max_attempts"] == 3

    response = await client.post(f"/jobs/{job_id}/retry")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending"
    assert body["max_attempts"] == 4
    assert body["error_message"] is None
    assert body["next_run_at"] is not None


@pytest.mark.asyncio
async def test_manual_retry_non_failed_returns_409(client: AsyncClient) -> None:
    created = await client.post(
        "/jobs",
        json={"job_type": "email", "payload": {"to": "a@example.com"}},
    )
    job_id = created.json()["id"]

    response = await client.post(f"/jobs/{job_id}/retry")
    assert response.status_code == 409
    assert "only failed jobs" in response.json()["detail"]


@pytest.mark.asyncio
async def test_manual_retry_unknown_id_returns_404(client: AsyncClient) -> None:
    response = await client.post(f"/jobs/{uuid.uuid4()}/retry")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_feeder_enqueues_after_manual_retry(
    client: AsyncClient,
    redis_client: Redis,
) -> None:
    job_id = await _force_permanently_failed(client)
    await redis_client.delete(JOBS_PENDING)

    response = await client.post(f"/jobs/{job_id}/retry")
    assert response.status_code == 200

    queue = await QueueClient.connect()
    try:
        promoted = await promote_ready_jobs(queue)
    finally:
        await queue.close()

    assert promoted == 1
    assert await redis_client.zscore(JOBS_PENDING, str(job_id)) is not None
