"""Tests for submit idempotency."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import func, select

from app.db.models import Job
from app.db.session import SessionLocal
from app.queue.keys import JOBS_PENDING
from app.services.idempotency import cleanup_expired_idempotency_keys

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
    assert first_body["id"]
    assert "job_type" in first_body

    second = await client.post("/jobs", json=payload, headers=headers)
    assert second.status_code == 200
    second_body = second.json()
    assert second_body == {"id": first_body["id"], "status": first_body["status"]}
    assert set(second_body.keys()) == {"id", "status"}

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


@pytest.mark.asyncio
async def test_different_keys_create_two_jobs(client: AsyncClient) -> None:
    body = {"job_type": "email", "payload": {}}
    a = await client.post(
        "/jobs", json=body, headers={"Idempotency-Key": "key-a"}
    )
    b = await client.post(
        "/jobs", json=body, headers={"Idempotency-Key": "key-b"}
    )
    assert a.status_code == 201
    assert b.status_code == 201
    assert a.json()["id"] != b.json()["id"]


@pytest.mark.asyncio
async def test_body_idempotency_key_is_ignored(client: AsyncClient) -> None:
    """Idempotency is header-only; body field must not dedupe."""
    body = {
        "job_type": "email",
        "payload": {},
        "idempotency_key": "body-key",
    }
    first = await client.post("/jobs", json=body)
    second = await client.post("/jobs", json=body)
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] != second.json()["id"]


@pytest.mark.asyncio
async def test_cleanup_nulls_keys_older_than_24h(client: AsyncClient) -> None:
    created = await client.post(
        "/jobs",
        json={"job_type": "email", "payload": {}},
        headers={"Idempotency-Key": "old-key"},
    )
    assert created.status_code == 201
    job_id = created.json()["id"]

    async with SessionLocal() as session:
        job = await session.get(Job, uuid.UUID(job_id))
        assert job is not None
        job.created_at = datetime.now(UTC) - timedelta(hours=25)
        await session.commit()

        cleared = await cleanup_expired_idempotency_keys(session)
        assert cleared == 1

        await session.refresh(job)
        assert job.idempotency_key is None

    reuse = await client.post(
        "/jobs",
        json={"job_type": "email", "payload": {}},
        headers={"Idempotency-Key": "old-key"},
    )
    assert reuse.status_code == 201
    assert reuse.json()["id"] != job_id
