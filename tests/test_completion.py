"""Worker completion — claim + handler + result stored."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, JobStatus, JobType
from app.db.session import SessionLocal
from app.queue.client import QueueClient
from app.queue.keys import priority_score

pytestmark = pytest.mark.usefixtures("clean_jobs")

ProcessNext = Callable[[], Coroutine[Any, Any, bool]]


@pytest.mark.asyncio
@patch("app.jobs.email.asyncio.sleep", new_callable=AsyncMock)
async def test_process_one_completes_job(
    _sleep: AsyncMock,
    db_session: AsyncSession,
    queue: QueueClient,
    process_next: ProcessNext,
) -> None:
    job = Job(
        job_type=JobType.email,
        payload={"to": "direct@example.com"},
        status=JobStatus.pending,
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
        assert done.progress_pct == 100
