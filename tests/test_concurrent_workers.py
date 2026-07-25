"""Multiple concurrent workers — Postgres claim allows only one winner."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, JobStatus, JobType
from app.db.session import SessionLocal
from app.worker.claim import claim_job

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

    async with SessionLocal() as session:
        row = await session.scalar(select(Job).where(Job.id == job_id))
        assert row is not None
        assert row.status == JobStatus.processing
        assert row.attempt_count == 1
