"""Idempotency — duplicate header key returns existing job; no re-enqueue."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import func, select

from app.db.models import Job
from app.db.session import SessionLocal
from app.queue.keys import JOBS_PENDING

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
async def test_empty_idempotency_key_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/jobs",
        json={"job_type": "email", "payload": {}},
        headers={"Idempotency-Key": "   "},
    )
    assert response.status_code == 422
