"""Story 2.6 — list jobs with status/type filters and pagination."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_all_jobs(client: AsyncClient, clean_jobs: None) -> None:
    created_ids: list[str] = []
    for job_type in ("email", "webhook", "email"):
        r = await client.post(
            "/jobs",
            json={"job_type": job_type, "payload": {}, "priority": 0},
        )
        assert r.status_code == 201
        created_ids.append(r.json()["id"])

    response = await client.get("/jobs")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["limit"] == 50
    assert body["offset"] == 0
    listed_ids = {item["id"] for item in body["items"]}
    assert set(created_ids) == listed_ids


@pytest.mark.asyncio
async def test_filter_by_status(client: AsyncClient, clean_jobs: None) -> None:
    pending = await client.post(
        "/jobs",
        json={"job_type": "email", "payload": {}, "priority": 0},
    )
    assert pending.status_code == 201
    pending_id = pending.json()["id"]

    to_cancel = await client.post(
        "/jobs",
        json={"job_type": "email", "payload": {}, "priority": 0},
    )
    cancelled_id = to_cancel.json()["id"]
    await client.post(f"/jobs/{cancelled_id}/cancel")

    response = await client.get("/jobs", params={"status": "pending"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert all(item["status"] == "pending" for item in body["items"])
    ids = {item["id"] for item in body["items"]}
    assert pending_id in ids
    assert cancelled_id not in ids


@pytest.mark.asyncio
async def test_filter_by_job_type(client: AsyncClient, clean_jobs: None) -> None:
    email = await client.post(
        "/jobs",
        json={"job_type": "email", "payload": {}, "priority": 0},
    )
    webhook = await client.post(
        "/jobs",
        json={"job_type": "webhook", "payload": {}, "priority": 0},
    )
    email_id = email.json()["id"]
    webhook_id = webhook.json()["id"]

    response = await client.get("/jobs", params={"job_type": "email"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert all(item["job_type"] == "email" for item in body["items"])
    ids = {item["id"] for item in body["items"]}
    assert email_id in ids
    assert webhook_id not in ids


@pytest.mark.asyncio
async def test_combined_filters(client: AsyncClient, clean_jobs: None) -> None:
    r = await client.post(
        "/jobs",
        json={"job_type": "report", "payload": {"name": "weekly"}, "priority": 0},
    )
    job_id = r.json()["id"]
    await client.post(
        "/jobs",
        json={"job_type": "email", "payload": {}, "priority": 0},
    )

    response = await client.get(
        "/jobs",
        params={"status": "pending", "job_type": "report"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert all(
        item["status"] == "pending" and item["job_type"] == "report"
        for item in body["items"]
    )
    assert job_id in {item["id"] for item in body["items"]}


@pytest.mark.asyncio
async def test_pagination_limit_offset(client: AsyncClient, clean_jobs: None) -> None:
    for i in range(5):
        r = await client.post(
            "/jobs",
            json={
                "job_type": "email",
                "payload": {"n": i},
                "priority": 0,
            },
        )
        assert r.status_code == 201

    page1 = await client.get("/jobs", params={"limit": 2, "offset": 0})
    assert page1.status_code == 200
    b1 = page1.json()
    assert b1["limit"] == 2
    assert b1["offset"] == 0
    assert len(b1["items"]) == 2
    assert b1["total"] == 5

    page2 = await client.get("/jobs", params={"limit": 2, "offset": 2})
    assert page2.status_code == 200
    b2 = page2.json()
    assert b2["offset"] == 2
    assert len(b2["items"]) == 2
    assert {i["id"] for i in b1["items"]}.isdisjoint(
        {i["id"] for i in b2["items"]}
    )


@pytest.mark.asyncio
async def test_invalid_status_filter_422(client: AsyncClient) -> None:
    response = await client.get("/jobs", params={"status": "not_a_status"})
    assert response.status_code == 422
