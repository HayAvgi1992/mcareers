"""Tests for GET /jobs/{id}."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.usefixtures("clean_jobs")


@pytest.mark.asyncio
async def test_get_job_returns_full_details(client: AsyncClient) -> None:
    created = await client.post(
        "/jobs",
        json={"job_type": "email", "payload": {"to": "a@example.com"}, "priority": 2},
    )
    assert created.status_code == 201
    job_id = created.json()["id"]

    response = await client.get(f"/jobs/{job_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == job_id
    assert body["job_type"] == "email"
    assert body["status"] == "pending"
    assert body["priority"] == 2
    assert body["payload"] == {"to": "a@example.com"}
    assert body["progress_pct"] == 0
    assert body["attempt_count"] == 0
    assert body["result"] is None
    assert body["error_message"] is None
    assert body["created_at"] is not None
    assert body["started_at"] is None
    assert body["completed_at"] is None


@pytest.mark.asyncio
async def test_get_job_unknown_id_returns_404(client: AsyncClient) -> None:
    missing = uuid.uuid4()
    response = await client.get(f"/jobs/{missing}")
    assert response.status_code == 404
    assert response.json()["detail"] == "Job not found"
