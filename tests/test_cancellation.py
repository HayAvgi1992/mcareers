"""Cancel pending jobs — removes Redis entry."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis

from app.queue.keys import JOBS_PENDING

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
