"""Worker crash recovery — reaper resets expired leases to pending."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, JobStatus, JobType
from app.db.session import SessionLocal
from app.queue.client import QueueClient
from app.worker.executor import process_one
from app.worker.feeder import promote_ready_jobs
from app.worker.reaper import reap_expired_leases

pytestmark = pytest.mark.usefixtures("clean_jobs")


@pytest.mark.asyncio
async def test_reaper_resets_expired_lease_to_pending(
    db_session: AsyncSession,
) -> None:
    job = Job(
        job_type=JobType.email,
        payload={"to": "stuck@example.com"},
        status=JobStatus.processing,
        worker_id="dead-worker",
        leased_until=datetime.now(UTC) - timedelta(seconds=1),
        attempt_count=1,
        started_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)
    job_id = job.id

    assert await reap_expired_leases() == 1

    async with SessionLocal() as session:
        refreshed = await session.scalar(select(Job).where(Job.id == job_id))
        assert refreshed is not None
        assert refreshed.status == JobStatus.pending
        assert refreshed.worker_id is None
        assert refreshed.leased_until is None
        assert refreshed.next_run_at is None
        assert refreshed.attempt_count == 1


@pytest.mark.asyncio
async def test_reaper_skips_active_lease(db_session: AsyncSession) -> None:
    job = Job(
        job_type=JobType.email,
        payload={},
        status=JobStatus.processing,
        worker_id="alive-worker",
        leased_until=datetime.now(UTC) + timedelta(minutes=5),
        attempt_count=1,
    )
    db_session.add(job)
    await db_session.commit()

    assert await reap_expired_leases() == 0

    await db_session.refresh(job)
    assert job.status == JobStatus.processing
    assert job.worker_id == "alive-worker"


@pytest.mark.asyncio
@patch("app.jobs.email.asyncio.sleep", new_callable=AsyncMock)
async def test_reaped_job_completes_via_feeder(
    _sleep: AsyncMock,
    db_session: AsyncSession,
    queue: QueueClient,
) -> None:
    job = Job(
        job_type=JobType.email,
        payload={"to": "recover@example.com"},
        status=JobStatus.processing,
        worker_id="crashed-worker",
        leased_until=datetime.now(UTC) - timedelta(seconds=5),
        attempt_count=1,
        max_attempts=3,
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)
    job_id = job.id

    assert await reap_expired_leases() == 1
    assert await promote_ready_jobs(queue) == 1
    assert await process_one(queue, worker_id="recovery-worker") is True

    async with SessionLocal() as session:
        done = await session.scalar(select(Job).where(Job.id == job_id))
        assert done is not None
        assert done.status == JobStatus.completed
        assert done.result["to"] == "recover@example.com"
        assert done.worker_id == "recovery-worker"
