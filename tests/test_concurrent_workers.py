"""Multiple concurrent workers — Postgres claim allows only one winner."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, JobStatus, JobType
from app.db.session import SessionLocal
from app.queue.client import QueueClient
from app.queue.keys import priority_score
from app.worker.claim import claim_job
from app.worker.executor import process_one

pytestmark = pytest.mark.usefixtures("clean_jobs")


@pytest.mark.asyncio
async def test_concurrent_claim_only_one_wins(db_session: AsyncSession) -> None:
    job = Job(
        job_type=JobType.email,
        payload={"to": "race@example.com"},
        status=JobStatus.pending,
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)
    job_id = job.id

    async def claim_as(worker_id: str) -> Job | None:
        async with SessionLocal() as session:
            return await claim_job(
                session, job_id, worker_id=worker_id, lease_seconds=60
            )

    first, second = await asyncio.gather(
        claim_as("worker-a"),
        claim_as("worker-b"),
    )

    winners = [c for c in (first, second) if c is not None]
    losers = [c for c in (first, second) if c is None]
    assert len(winners) == 1
    assert len(losers) == 1
    assert winners[0].status == JobStatus.processing
    assert winners[0].worker_id in {"worker-a", "worker-b"}

    async with SessionLocal() as session:
        row = await session.scalar(select(Job).where(Job.id == job_id))
        assert row is not None
        assert row.status == JobStatus.processing
        assert row.attempt_count == 1


@pytest.mark.asyncio
@patch("app.jobs.email.asyncio.sleep", new_callable=AsyncMock)
async def test_concurrent_process_one_runs_handler_once(
    _sleep: AsyncMock,
    db_session: AsyncSession,
    queue: QueueClient,
) -> None:
    """Two workers race one queued job — only one executes the handler."""
    job = Job(
        job_type=JobType.email,
        payload={"to": "once@example.com"},
        status=JobStatus.pending,
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)
    job_id = job.id
    await queue.enqueue(job_id, priority_score(job.priority, job.created_at))

    run_mock = AsyncMock(return_value={"status": "sent", "to": "once@example.com"})
    with patch("app.jobs.email.run", new=run_mock):
        results = await asyncio.gather(
            process_one(queue, worker_id="worker-a"),
            process_one(queue, worker_id="worker-b"),
        )

    assert sorted(results) == [False, True]
    assert run_mock.await_count == 1

    async with SessionLocal() as session:
        done = await session.scalar(select(Job).where(Job.id == job_id))
        assert done is not None
        assert done.status == JobStatus.completed
        assert done.attempt_count == 1
        assert done.result["to"] == "once@example.com"
