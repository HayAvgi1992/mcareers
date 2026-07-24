"""Tests for priority ordering in the dispatch queue."""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis

from app.queue.client import QueueClient
from app.queue.keys import JOBS_PENDING
from app.worker.executor import process_one

pytestmark = pytest.mark.usefixtures("clean_jobs")


@pytest.mark.asyncio
async def test_higher_priority_is_dequeued_first(
    client: AsyncClient,
    redis_client: Redis,
) -> None:
    """Submit low then high; high must be first out of the ZSET."""
    low = await client.post(
        "/jobs",
        json={
            "job_type": "email",
            "payload": {"to": "low@example.com"},
            "priority": 1,
        },
    )
    high = await client.post(
        "/jobs",
        json={
            "job_type": "email",
            "payload": {"to": "high@example.com"},
            "priority": 10,
        },
    )
    assert low.status_code == 201
    assert high.status_code == 201
    low_id = low.json()["id"]
    high_id = high.json()["id"]

    ordered = await redis_client.zrange(JOBS_PENDING, 0, -1)
    assert ordered[0] == high_id
    assert ordered[1] == low_id

    queue = await QueueClient.connect()
    try:
        assert await queue.dequeue() == uuid.UUID(high_id)
        assert await queue.dequeue() == uuid.UUID(low_id)
    finally:
        await queue.close()


@pytest.mark.asyncio
async def test_same_priority_is_fifo_by_created_at(
    client: AsyncClient,
    redis_client: Redis,
) -> None:
    first = await client.post(
        "/jobs",
        json={
            "job_type": "email",
            "payload": {"to": "first@example.com"},
            "priority": 5,
        },
    )
    # Ensure distinct created_at epoch ms for FIFO score ordering.
    await asyncio.sleep(0.02)
    second = await client.post(
        "/jobs",
        json={
            "job_type": "email",
            "payload": {"to": "second@example.com"},
            "priority": 5,
        },
    )
    first_id = first.json()["id"]
    second_id = second.json()["id"]

    ordered = await redis_client.zrange(JOBS_PENDING, 0, -1)
    assert ordered[0] == first_id
    assert ordered[1] == second_id

    queue = await QueueClient.connect()
    try:
        assert await queue.dequeue() == uuid.UUID(first_id)
        assert await queue.dequeue() == uuid.UUID(second_id)
    finally:
        await queue.close()


@pytest.mark.asyncio
@patch("app.jobs.email.asyncio.sleep", new_callable=AsyncMock)
async def test_higher_priority_completes_before_lower(
    _sleep: AsyncMock,
    client: AsyncClient,
) -> None:
    """End-to-end: process_one runs high-priority job first."""
    low = await client.post(
        "/jobs",
        json={
            "job_type": "email",
            "payload": {"to": "low@example.com"},
            "priority": 1,
        },
    )
    high = await client.post(
        "/jobs",
        json={
            "job_type": "email",
            "payload": {"to": "high@example.com"},
            "priority": 10,
        },
    )
    low_id = low.json()["id"]
    high_id = high.json()["id"]

    queue = await QueueClient.connect()
    try:
        assert await process_one(queue, worker_id="priority-worker") is True
    finally:
        await queue.close()

    high_body = (await client.get(f"/jobs/{high_id}")).json()
    low_body = (await client.get(f"/jobs/{low_id}")).json()
    assert high_body["status"] == "completed"
    assert low_body["status"] == "pending"


@pytest.mark.asyncio
async def test_submit_accepts_priority_default_zero(client: AsyncClient) -> None:
    response = await client.post(
        "/jobs",
        json={"job_type": "email", "payload": {"to": "default@example.com"}},
    )
    assert response.status_code == 201
    assert response.json()["priority"] == 0
