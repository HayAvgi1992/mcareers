"""Tests for worker executor completion path."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, JobStatus, JobType
from app.queue.client import QueueClient
from app.worker.claim import claim_job
from app.worker.executor import process_one

pytestmark = pytest.mark.usefixtures("clean_jobs")


@pytest.mark.asyncio
@patch("app.jobs.email.asyncio.sleep", new_callable=AsyncMock)
async def test_process_one_completes_submitted_job(
    _sleep: AsyncMock,
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    created = await client.post(
        "/jobs",
        json={"job_type": "email", "payload": {"to": "a@example.com"}},
    )
    assert created.status_code == 201
    job_id = uuid.UUID(created.json()["id"])

    queue = await QueueClient.connect()
    try:
        assert await process_one(queue, worker_id="test-worker-1") is True
    finally:
        await queue.close()

    job = await db_session.scalar(select(Job).where(Job.id == job_id))
    assert job is not None
    assert job.status == JobStatus.completed
    assert job.result is not None
    assert job.result["status"] == "sent"
    assert job.started_at is not None
    assert job.completed_at is not None
    assert job.progress_pct == 100
    assert job.worker_id == "test-worker-1"


@pytest.mark.asyncio
@patch("app.jobs.email.asyncio.sleep", new_callable=AsyncMock)
async def test_get_job_shows_completed_result(
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
        await process_one(queue, worker_id="test-worker-2")
    finally:
        await queue.close()

    response = await client.get(f"/jobs/{job_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["result"]["to"] == "b@example.com"
    assert body["started_at"] is not None
    assert body["completed_at"] is not None


@pytest.mark.asyncio
async def test_claim_skips_non_pending_job(db_session: AsyncSession) -> None:
    job = Job(
        job_type=JobType.email,
        payload={},
        status=JobStatus.cancelled,
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)

    claimed = await claim_job(
        db_session, job.id, worker_id="w", lease_seconds=60
    )
    assert claimed is None


@pytest.mark.asyncio
async def test_process_one_empty_queue_returns_false() -> None:
    queue = await QueueClient.connect()
    try:
        assert await process_one(queue, worker_id="test-worker") is False
    finally:
        await queue.close()
