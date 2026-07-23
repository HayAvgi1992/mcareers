"""Tests for POST /jobs submission."""

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
async def test_submit_job_returns_201_and_id(client: AsyncClient) -> None:
    response = await client.post(
        "/jobs",
        json={"job_type": "email", "payload": {"to": "a@example.com"}},
    )
    assert response.status_code == 201
    body = response.json()
    assert uuid.UUID(body["id"])
    assert body["job_type"] == "email"
    assert body["status"] == "pending"
    assert body["payload"] == {"to": "a@example.com"}


@pytest.mark.asyncio
async def test_submit_job_persists_pending_row(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    response = await client.post(
        "/jobs",
        json={"job_type": "report", "payload": {"name": "weekly"}},
    )
    assert response.status_code == 201
    job_id = uuid.UUID(response.json()["id"])

    job = await db_session.scalar(select(Job).where(Job.id == job_id))
    assert job is not None
    assert job.status == JobStatus.pending
    assert job.job_type.value == "report"
    assert job.payload == {"name": "weekly"}


@pytest.mark.asyncio
async def test_submit_job_enqueues_in_redis(
    client: AsyncClient,
    redis_client: Redis,
) -> None:
    response = await client.post(
        "/jobs",
        json={"job_type": "webhook", "payload": {"url": "https://example.com"}},
    )
    assert response.status_code == 201
    job_id = response.json()["id"]

    score = await redis_client.zscore(JOBS_PENDING, job_id)
    assert score is not None


@pytest.mark.asyncio
async def test_submit_rejects_unknown_job_type(client: AsyncClient) -> None:
    response = await client.post(
        "/jobs",
        json={"job_type": "not_a_real_type", "payload": {}},
    )
    assert response.status_code == 422
