"""GET /health — connectivity + queue/job counts."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.usefixtures("clean_jobs")


@pytest.mark.asyncio
async def test_health_ok_with_stats(client: AsyncClient) -> None:
    await client.post(
        "/jobs",
        json={"job_type": "email", "payload": {"to": "a@example.com"}},
    )
    await client.post(
        "/jobs",
        json={"job_type": "webhook", "payload": {"url": "https://example.com"}},
    )

    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["redis"] == "ok"
    assert body["jobs"]["pending"] == 2
    assert body["jobs"]["processing"] == 0
    assert body["jobs"]["failed"] == 0
    assert body["queue"]["pending_depth"] == 2
    assert body["queue"]["scheduled_depth"] == 0


@pytest.mark.asyncio
async def test_health_503_when_redis_down(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.main import app

    monkeypatch.setattr(
        app.state.queue, "ping", AsyncMock(side_effect=ConnectionError("down"))
    )

    response = await client.get("/health")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["redis"] == "error"
    assert body["database"] == "ok"
