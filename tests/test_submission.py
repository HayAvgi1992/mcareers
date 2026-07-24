"""Submit job — happy path + validation failure."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, JobStatus
from app.queue.keys import JOBS_PENDING

pytestmark = pytest.mark.usefixtures("clean_jobs")


@pytest.mark.asyncio
async def test_submit_job_persists_and_enqueues(
    client: AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
) -> None:
    response = await client.post(
        "/jobs",
        json={"job_type": "email", "payload": {"to": "a@example.com"}, "priority": 2},
    )
    assert response.status_code == 201
    body = response.json()
    job_id = uuid.UUID(body["id"])
    assert body["status"] == "pending"
    assert body["job_type"] == "email"
    assert body["priority"] == 2

    job = await db_session.scalar(select(Job).where(Job.id == job_id))
    assert job is not None
    assert job.status == JobStatus.pending
    assert await redis_client.zscore(JOBS_PENDING, str(job_id)) is not None


@pytest.mark.asyncio
async def test_submit_rejects_unknown_job_type(client: AsyncClient) -> None:
    response = await client.post(
        "/jobs",
        json={"job_type": "not_a_real_type", "payload": {}},
    )
    assert response.status_code == 422
