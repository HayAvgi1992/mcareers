"""Health endpoint — connectivity, queue stats, live workers."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.queue.client import QueueClient

pytestmark = pytest.mark.usefixtures("clean_jobs")


@pytest.mark.asyncio
async def test_health_lists_alive_workers(
    client: AsyncClient,
    queue: QueueClient,
) -> None:
    await queue.worker_heartbeat("worker-a")
    await queue.worker_heartbeat("worker-b")

    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["queue"]["pending_depth"] == 0
    assert body["workers"]["alive_count"] == 2
    ids = {w["worker_id"] for w in body["workers"]["alive"]}
    assert ids == {"worker-a", "worker-b"}
    assert all("last_seen_at" in w for w in body["workers"]["alive"])


@pytest.mark.asyncio
async def test_stale_workers_are_pruned(queue: QueueClient) -> None:
    now = 1_700_000_000.0
    await queue.worker_heartbeat("fresh", now=now, ttl_seconds=15)
    await queue.worker_heartbeat("stale", now=now - 60, ttl_seconds=15)
    # Next beat prunes members older than ttl.
    await queue.worker_heartbeat("fresh", now=now, ttl_seconds=15)

    alive = await queue.list_alive_workers(now=now, ttl_seconds=15)
    assert [worker_id for worker_id, _ in alive] == ["fresh"]
