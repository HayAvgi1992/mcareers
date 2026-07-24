"""Tests for worker executor completion path (Story 1.4 / 2.7)."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Coroutine
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, JobStatus, JobType
from app.db.session import SessionLocal
from app.jobs.base import HandlerError
from app.queue.client import QueueClient
from app.queue.keys import JOBS_PENDING, priority_score
from app.worker.claim import claim_job

pytestmark = pytest.mark.usefixtures("clean_jobs")

ProcessNext = Callable[[], Coroutine[Any, Any, bool]]


@pytest.mark.asyncio
@patch("app.jobs.email.asyncio.sleep", new_callable=AsyncMock)
async def test_process_one_completes_submitted_job(
    _sleep: AsyncMock,
    client: AsyncClient,
    process_next: ProcessNext,
) -> None:
    created = await client.post(
        "/jobs",
        json={"job_type": "email", "payload": {"to": "a@example.com"}},
    )
    assert created.status_code == 201
    job_id = uuid.UUID(created.json()["id"])

    assert await process_next() is True

    async with SessionLocal() as session:
        job = await session.scalar(select(Job).where(Job.id == job_id))
        assert job is not None
        assert job.status == JobStatus.completed
        assert job.result is not None
        assert job.result["status"] == "sent"
        assert job.started_at is not None
        assert job.completed_at is not None
        assert job.progress_pct == 100
        assert job.worker_id == "test-worker"


@pytest.mark.asyncio
@patch("app.jobs.email.asyncio.sleep", new_callable=AsyncMock)
async def test_process_one_completes_job_without_http(
    _sleep: AsyncMock,
    db_session: AsyncSession,
    queue: QueueClient,
    process_next: ProcessNext,
) -> None:
    """Worker path with no API: insert + enqueue + process_one."""
    job = Job(
        job_type=JobType.email,
        payload={"to": "direct@example.com"},
        status=JobStatus.pending,
        priority=0,
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)
    job_id = job.id

    await queue.enqueue(job_id, priority_score(job.priority, job.created_at))
    assert await process_next() is True

    async with SessionLocal() as session:
        done = await session.scalar(select(Job).where(Job.id == job_id))
        assert done is not None
        assert done.status == JobStatus.completed
        assert done.result["to"] == "direct@example.com"
        assert done.worker_id == "test-worker"


@pytest.mark.asyncio
@patch("app.jobs.email.asyncio.sleep", new_callable=AsyncMock)
async def test_get_job_shows_completed_result(
    _sleep: AsyncMock,
    client: AsyncClient,
    process_next: ProcessNext,
) -> None:
    created = await client.post(
        "/jobs",
        json={"job_type": "email", "payload": {"to": "b@example.com"}},
    )
    job_id = created.json()["id"]

    await process_next()

    response = await client.get(f"/jobs/{job_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["result"]["to"] == "b@example.com"
    assert body["started_at"] is not None
    assert body["completed_at"] is not None


@pytest.mark.asyncio
@patch("app.jobs.report.asyncio.sleep", new_callable=AsyncMock)
async def test_process_one_completes_report_job(
    _sleep: AsyncMock,
    db_session: AsyncSession,
    queue: QueueClient,
    process_next: ProcessNext,
) -> None:
    job = Job(
        job_type=JobType.report,
        payload={"name": "weekly"},
        status=JobStatus.pending,
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)

    await queue.enqueue(job.id, priority_score(job.priority, job.created_at))
    assert await process_next() is True

    async with SessionLocal() as session:
        done = await session.scalar(select(Job).where(Job.id == job.id))
        assert done is not None
        assert done.status == JobStatus.completed
        assert done.result is not None


@pytest.mark.asyncio
@patch(
    "app.jobs.webhook.run",
    new_callable=AsyncMock,
    side_effect=HandlerError("delivery failed"),
)
async def test_process_one_schedules_retry_on_handler_error(
    _run: AsyncMock,
    db_session: AsyncSession,
    queue: QueueClient,
    process_next: ProcessNext,
    redis_client: Redis,
) -> None:
    """Failure updates DB only; executor does not re-enqueue."""
    job = Job(
        job_type=JobType.webhook,
        payload={"url": "https://example.com"},
        status=JobStatus.pending,
        max_attempts=3,
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)
    job_id = job.id

    await queue.enqueue(job_id, priority_score(job.priority, job.created_at))
    assert await process_next() is True

    async with SessionLocal() as session:
        failed = await session.scalar(select(Job).where(Job.id == job_id))
        assert failed is not None
        assert failed.status == JobStatus.pending
        assert failed.attempt_count == 1
        assert failed.next_run_at is not None
        assert failed.error_message == "delivery failed"

    assert await redis_client.zscore(JOBS_PENDING, str(job_id)) is None


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
async def test_process_one_empty_queue_returns_false(
    process_next: ProcessNext,
) -> None:
    assert await process_next() is False
