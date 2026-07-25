"""Idempotency — duplicate key returns existing job; no re-enqueue."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import func, select

from app.db.models import Job, JobStatus, JobType
from app.db.session import SessionLocal
from app.queue.keys import JOBS_PENDING
from app.services.idempotency import IDEMPOTENCY_TTL
from app.worker.idempotency_cleanup import run_cleanup_once

pytestmark = pytest.mark.usefixtures("clean_jobs")


@pytest.mark.asyncio
async def test_duplicate_idempotency_key_returns_same_job(
    client: AsyncClient,
    redis_client: Redis,
) -> None:
    payload = {"job_type": "email", "payload": {"to": "a@example.com"}}
    headers = {"Idempotency-Key": "client-req-1"}

    first = await client.post("/jobs", json=payload, headers=headers)
    assert first.status_code == 201
    first_body = first.json()

    second = await client.post("/jobs", json=payload, headers=headers)
    assert second.status_code == 200
    assert second.json() == {"id": first_body["id"], "status": first_body["status"]}

    async with SessionLocal() as session:
        count = await session.scalar(select(func.count()).select_from(Job))
    assert count == 1
    assert await redis_client.zcard(JOBS_PENDING) == 1


@pytest.mark.asyncio
async def test_cleanup_nulls_keys_older_than_ttl() -> None:
    async with SessionLocal() as session:
        old = Job(
            job_type=JobType.email,
            payload={"to": "old@example.com"},
            status=JobStatus.completed,
            idempotency_key="reuse-me-later",
            created_at=datetime.now(UTC) - IDEMPOTENCY_TTL - timedelta(minutes=1),
        )
        fresh = Job(
            job_type=JobType.email,
            payload={"to": "fresh@example.com"},
            status=JobStatus.pending,
            idempotency_key="still-fresh",
        )
        session.add_all([old, fresh])
        await session.commit()
        old_id, fresh_id = old.id, fresh.id

    assert await run_cleanup_once() == 1

    async with SessionLocal() as session:
        old_job = await session.scalar(select(Job).where(Job.id == old_id))
        fresh_job = await session.scalar(select(Job).where(Job.id == fresh_id))
        assert old_job is not None and old_job.idempotency_key is None
        assert fresh_job is not None and fresh_job.idempotency_key == "still-fresh"
