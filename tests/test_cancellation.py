"""Cancel pending jobs — removes Redis entry; rejects non-pending."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis

from app.queue.client import QueueClient
from app.queue.keys import JOBS_PENDING
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
    assert response.json()["status"] == "cancelled"
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

    response = await client.post(f"/jobs/{job_id}/cancel")
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_cancel_unknown_id_returns_404(client: AsyncClient) -> None:
    response = await client.post(f"/jobs/{uuid.uuid4()}/cancel")
    assert response.status_code == 404
