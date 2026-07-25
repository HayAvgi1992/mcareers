"""Graceful worker shutdown — finish in-flight job; pick up no new work."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, JobStatus, JobType
from app.db.session import SessionLocal
from app.queue.client import QueueClient
from app.queue.keys import priority_score
from app.worker.executor import process_one, run_executor_loop
from app.worker.feeder import run_feeder_loop

pytestmark = pytest.mark.usefixtures("clean_jobs")


@pytest.mark.asyncio
async def test_process_one_skips_dequeue_when_stop_set(
    db_session: AsyncSession,
    queue: QueueClient,
) -> None:
    job = Job(
        job_type=JobType.email,
        payload={"to": "skip@example.com"},
        status=JobStatus.pending,
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)
    await queue.enqueue(job.id, priority_score(job.priority, job.created_at))

    stop = asyncio.Event()
    stop.set()

    assert await process_one(queue, worker_id="shutdown-test", stop=stop) is False

    async with SessionLocal() as session:
        still = await session.scalar(select(Job).where(Job.id == job.id))
        assert still is not None
        assert still.status == JobStatus.pending


@pytest.mark.asyncio
async def test_executor_finishes_inflight_then_stops(
    db_session: AsyncSession,
    queue: QueueClient,
) -> None:
    first = Job(
        job_type=JobType.email,
        payload={"to": "first@example.com"},
        status=JobStatus.pending,
        priority=10,
    )
    second = Job(
        job_type=JobType.email,
        payload={"to": "second@example.com"},
        status=JobStatus.pending,
        priority=1,
    )
    db_session.add_all([first, second])
    await db_session.commit()
    await db_session.refresh(first)
    await db_session.refresh(second)
    first_id, second_id = first.id, second.id

    await queue.enqueue(first.id, priority_score(first.priority, first.created_at))
    await queue.enqueue(second.id, priority_score(second.priority, second.created_at))

    stop = asyncio.Event()
    started = asyncio.Event()

    async def slow_run(job: Job) -> dict[str, Any]:
        started.set()
        stop.set()  # shutdown mid-job
        await asyncio.sleep(0.05)
        return {"status": "sent", "to": job.payload.get("to")}

    with patch("app.jobs.email.run", new=AsyncMock(side_effect=slow_run)):
        task = asyncio.create_task(
            run_executor_loop(queue, worker_id="shutdown-test", stop=stop)
        )
        await asyncio.wait_for(started.wait(), timeout=2)
        await asyncio.wait_for(task, timeout=2)

    async with SessionLocal() as session:
        done = await session.scalar(select(Job).where(Job.id == first_id))
        leftover = await session.scalar(select(Job).where(Job.id == second_id))
        assert done is not None
        assert done.status == JobStatus.completed
        assert leftover is not None
        assert leftover.status == JobStatus.pending


@pytest.mark.asyncio
async def test_feeder_stops_on_shutdown(queue: QueueClient) -> None:
    stop = asyncio.Event()
    stop.set()
    task = asyncio.create_task(run_feeder_loop(queue, stop))
    await asyncio.wait_for(task, timeout=1)
