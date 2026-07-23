"""Tests for the DB → Redis feeder."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, JobStatus, JobType
from app.queue.client import QueueClient
from app.queue.keys import JOBS_PENDING, priority_score
from app.worker.executor import process_one
from app.worker.feeder import promote_ready_jobs

pytestmark = pytest.mark.usefixtures("clean_jobs")


@pytest.mark.asyncio
async def test_feeder_promotes_db_only_pending_job(
    db_session: AsyncSession,
    redis_client: Redis,
) -> None:
    """Recovery path: job in DB but never enqueued by API."""
    job = Job(
        job_type=JobType.email,
        payload={"to": "a@example.com"},
        status=JobStatus.pending,
        priority=0,
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)

    assert await redis_client.zscore(JOBS_PENDING, str(job.id)) is None

    queue = await QueueClient.connect()
    try:
        promoted = await promote_ready_jobs(queue)
    finally:
        await queue.close()

    assert promoted == 1
    score = await redis_client.zscore(JOBS_PENDING, str(job.id))
    assert score is not None
    assert score == priority_score(job.priority, job.created_at)


@pytest.mark.asyncio
async def test_feeder_skips_future_next_run_at(
    db_session: AsyncSession,
    redis_client: Redis,
) -> None:
    job = Job(
        job_type=JobType.webhook,
        payload={"url": "https://example.com"},
        status=JobStatus.pending,
        next_run_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)

    queue = await QueueClient.connect()
    try:
        promoted = await promote_ready_jobs(queue)
    finally:
        await queue.close()

    assert promoted == 0
    assert await redis_client.zscore(JOBS_PENDING, str(job.id)) is None


@pytest.mark.asyncio
async def test_feeder_priority_scores_higher_first(
    db_session: AsyncSession,
    redis_client: Redis,
) -> None:
    low = Job(job_type=JobType.email, payload={}, status=JobStatus.pending, priority=1)
    high = Job(job_type=JobType.email, payload={}, status=JobStatus.pending, priority=10)
    db_session.add_all([low, high])
    await db_session.commit()
    await db_session.refresh(low)
    await db_session.refresh(high)

    queue = await QueueClient.connect()
    try:
        await promote_ready_jobs(queue)
    finally:
        await queue.close()

    low_score = await redis_client.zscore(JOBS_PENDING, str(low.id))
    high_score = await redis_client.zscore(JOBS_PENDING, str(high.id))
    assert high_score is not None and low_score is not None
    assert high_score < low_score  # ZPOPMIN pops lowest score first


@pytest.mark.asyncio
async def test_feeder_does_not_duplicate_existing_redis_member(
    db_session: AsyncSession,
) -> None:
    job = Job(job_type=JobType.report, payload={}, status=JobStatus.pending)
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)

    queue = await QueueClient.connect()
    try:
        assert await promote_ready_jobs(queue) == 1
        assert await promote_ready_jobs(queue) == 0
    finally:
        await queue.close()


@pytest.mark.asyncio
@patch("app.jobs.email.asyncio.sleep", new_callable=AsyncMock)
async def test_feeder_then_executor_completes_db_only_job(
    _sleep: AsyncMock,
    db_session: AsyncSession,
) -> None:
    job = Job(
        job_type=JobType.email,
        payload={"to": "recover@example.com"},
        status=JobStatus.pending,
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)
    job_id = job.id

    queue = await QueueClient.connect()
    try:
        await promote_ready_jobs(queue)
        assert await process_one(queue, worker_id="feeder-test") is True
    finally:
        await queue.close()

    from sqlalchemy import select

    from app.db.session import SessionLocal

    async with SessionLocal() as session:
        refreshed = await session.scalar(select(Job).where(Job.id == job_id))
        assert refreshed is not None
        assert refreshed.status == JobStatus.completed
        assert refreshed.result is not None
