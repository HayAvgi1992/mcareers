"""Tests for POST /jobs submission (Story 1.1 / 2.7)."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import JobCreate
from app.db.models import Job, JobStatus, JobType
from app.queue.client import QueueClient
from app.queue.keys import JOBS_PENDING
from app.services import job_service

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
    assert body["priority"] == 0
    assert body["attempt_count"] == 0


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
async def test_submit_via_service_without_http(
    db_session: AsyncSession,
    queue: QueueClient,
    redis_client: Redis,
) -> None:
    """Submission path is testable at the service layer (no API)."""
    job, created = await job_service.submit_job(
        db_session,
        queue,
        JobCreate(
            job_type=JobType.email,
            payload={"to": "svc@example.com"},
            priority=3,
        ),
    )
    assert created is True
    assert job.status == JobStatus.pending
    assert job.priority == 3
    assert await redis_client.zscore(JOBS_PENDING, str(job.id)) is not None


@pytest.mark.asyncio
async def test_submit_defaults_empty_payload(client: AsyncClient) -> None:
    response = await client.post("/jobs", json={"job_type": "batch"})
    assert response.status_code == 201
    assert response.json()["payload"] == {}


@pytest.mark.asyncio
async def test_submit_rejects_unknown_job_type(client: AsyncClient) -> None:
    response = await client.post(
        "/jobs",
        json={"job_type": "not_a_real_type", "payload": {}},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_submit_rejects_priority_out_of_bounds(client: AsyncClient) -> None:
    high = await client.post(
        "/jobs",
        json={"job_type": "email", "payload": {}, "priority": 1001},
    )
    low = await client.post(
        "/jobs",
        json={"job_type": "email", "payload": {}, "priority": -1001},
    )
    assert high.status_code == 422
    assert low.status_code == 422


@pytest.mark.asyncio
async def test_submit_rejects_missing_job_type(client: AsyncClient) -> None:
    response = await client.post("/jobs", json={"payload": {}})
    assert response.status_code == 422
