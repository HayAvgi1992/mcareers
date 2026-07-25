"""Submit rejects invalid / oversized job payloads."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.api.schemas import PAYLOAD_MAX_BYTES

pytestmark = pytest.mark.usefixtures("clean_jobs")


@pytest.mark.asyncio
async def test_email_payload_requires_to(client: AsyncClient) -> None:
    response = await client.post(
        "/jobs",
        json={"job_type": "email", "payload": {}},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_webhook_payload_requires_http_url(client: AsyncClient) -> None:
    response = await client.post(
        "/jobs",
        json={"job_type": "webhook", "payload": {"url": "not-a-url"}},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_batch_payload_requires_items_list(client: AsyncClient) -> None:
    response = await client.post(
        "/jobs",
        json={"job_type": "batch", "payload": {"items": "nope"}},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_payload_size_limit(client: AsyncClient) -> None:
    # Build a payload that exceeds the byte cap after JSON encoding.
    oversized = "x" * (PAYLOAD_MAX_BYTES + 1)
    response = await client.post(
        "/jobs",
        json={"job_type": "report", "payload": {"name": oversized}},
    )
    assert response.status_code == 422
