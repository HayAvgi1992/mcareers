"""Worker completion — executor path independent of HTTP submit."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Coroutine
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
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
        assert done.completed_at is not None


@pytest.mark.asyncio
@patch("app.jobs.email.asyncio.sleep", new_callable=AsyncMock)
async def test_get_job_returns_completed_result(
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


@pytest.mark.asyncio
async def test_get_job_unknown_id_returns_404(client: AsyncClient) -> None:
    response = await client.get(f"/jobs/{uuid.uuid4()}")
    assert response.status_code == 404
