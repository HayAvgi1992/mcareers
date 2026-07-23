"""Atomic DB claim: pending → processing with lease."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, JobStatus


async def claim_job(
    session: AsyncSession,
    job_id: uuid.UUID,
    worker_id: str,
    lease_seconds: int,
) -> Job | None:
    """
    Conditionally claim a pending job. Returns the job if this worker won;
    None if already taken, cancelled, or not yet due (Postgres wins).
    """
    leased_until = datetime.now(UTC) + timedelta(seconds=lease_seconds)
    stmt = (
        update(Job)
        .where(
            Job.id == job_id,
            Job.status == JobStatus.pending,
            or_(Job.next_run_at.is_(None), Job.next_run_at <= func.now()),
        )
        .values(
            status=JobStatus.processing,
            worker_id=worker_id,
            leased_until=leased_until,
            started_at=func.now(),
            attempt_count=Job.attempt_count + 1,
        )
        .returning(Job)
    )
    result = await session.execute(stmt)
    job = result.scalar_one_or_none()
    if job is None:
        await session.rollback()
        return None
    await session.commit()
    return job
