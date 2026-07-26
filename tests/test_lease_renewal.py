"""Lease renewal extends leased_until for the owning worker only."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, JobStatus, JobType
from app.db.session import SessionLocal
from app.worker.claim import claim_job, renew_job_lease

pytestmark = pytest.mark.usefixtures("clean_jobs")


@pytest.mark.asyncio
async def test_renew_lease_extends_leased_until(db_session: AsyncSession) -> None:
    job = Job(
        job_type=JobType.email,
        payload={"to": "lease@example.com"},
        status=JobStatus.pending,
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)
    job_id = job.id

    claimed = await claim_job(
        db_session, job_id, worker_id="w1", lease_seconds=30
    )
    assert claimed is not None
    original = claimed.leased_until
    assert original is not None

    # Force an earlier lease so the renewal is visibly later.
    async with SessionLocal() as session:
        row = await session.scalar(select(Job).where(Job.id == job_id))
        assert row is not None
        row.leased_until = datetime.now(UTC) + timedelta(seconds=5)
        await session.commit()
        before = row.leased_until

    renewed = await renew_job_lease(job_id, "w1", lease_seconds=60)
    assert renewed is not None
    assert renewed > before

    # Wrong worker cannot renew.
    assert await renew_job_lease(job_id, "other-worker", lease_seconds=60) is None
