"""Priority ordering in the Redis dispatch queue."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis

from app.queue.client import QueueClient
from app.queue.keys import JOBS_PENDING

pytestmark = pytest.mark.usefixtures("clean_jobs")


@pytest.mark.asyncio
async def test_higher_priority_is_dequeued_first(
    client: AsyncClient,
    redis_client: Redis,
) -> None:
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

    ordered = await redis_client.zrange(JOBS_PENDING, 0, -1)
    assert ordered[0] == high_id
    assert ordered[1] == low_id

    queue = await QueueClient.connect()
    try:
        assert await queue.dequeue() == uuid.UUID(high_id)
        assert await queue.dequeue() == uuid.UUID(low_id)
    finally:
        await queue.close()
