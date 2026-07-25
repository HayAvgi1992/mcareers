"""Job timeout — overrun schedules DB-driven retry."""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.config import settings
from app.db.models import Job, JobStatus
from app.db.session import SessionLocal
from app.worker.executor import process_one

pytestmark = pytest.mark.usefixtures("clean_jobs")


@pytest.mark.asyncio
async def test_timeout_schedules_retry(client: AsyncClient, queue) -> None:
    created = await client.post(
        "/jobs",
        json={"job_type": "email", "payload": {"to": "slow@example.com"}},
    )
    job_id = uuid.UUID(created.json()["id"])

    async def _slow(_job):
        await asyncio.sleep(1.0)
        return {"status": "sent"}

    with (
        patch.object(settings, "job_timeout_seconds", 0.05),
        patch("app.jobs.email.run", new=AsyncMock(side_effect=_slow)),
    ):
        assert await process_one(queue, worker_id="timeout-worker") is True

    async with SessionLocal() as session:
        job = await session.scalar(select(Job).where(Job.id == job_id))
        assert job is not None
        assert job.status == JobStatus.pending
        assert job.attempt_count == 1
        assert job.next_run_at is not None
        assert job.error_message is not None
        assert "timed out" in job.error_message
