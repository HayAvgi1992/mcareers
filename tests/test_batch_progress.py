"""Batch progress — mid-run progress_pct visible via GET."""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.models import Job
from app.db.session import SessionLocal
from app.worker.executor import process_one

pytestmark = pytest.mark.usefixtures("clean_jobs")


@pytest.mark.asyncio
async def test_batch_progress_persisted_and_exposed_via_get(
    client: AsyncClient, queue
) -> None:
    created = await client.post(
        "/jobs",
        json={
            "job_type": "batch",
            "payload": {"items": ["a", "b", "c", "d"]},
        },
    )
    job_id = uuid.UUID(created.json()["id"])
    mid_values: list[int] = []

    async def run_with_checks(job: Job, report=None):
        assert report is not None
        await report(25)
        async with SessionLocal() as session:
            row = await session.scalar(select(Job).where(Job.id == job.id))
            assert row is not None
            mid_values.append(row.progress_pct)
        get_mid = await client.get(f"/jobs/{job_id}")
        assert get_mid.status_code == 200
        assert get_mid.json()["progress_pct"] == 25
        assert get_mid.json()["status"] == "processing"

        await report(75)
        async with SessionLocal() as session:
            row = await session.scalar(select(Job).where(Job.id == job.id))
            assert row is not None
            mid_values.append(row.progress_pct)
        return {"status": "processed", "processed": 4, "failed": 0}

    with patch("app.jobs.batch.run", new=run_with_checks):
        assert await process_one(queue, worker_id="progress-worker") is True

    assert mid_values == [25, 75]

    done = await client.get(f"/jobs/{job_id}")
    assert done.status_code == 200
    body = done.json()
    assert body["status"] == "completed"
    assert body["progress_pct"] == 100
