"""Structured JSON logging — required transition events emit job context."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from httpx import AsyncClient
from structlog.testing import capture_logs

from app.db.models import Job, JobStatus
from app.db.session import SessionLocal
from app.jobs.base import HandlerError
from app.queue.client import QueueClient
from app.queue.keys import priority_score
from app.worker.executor import process_one

pytestmark = pytest.mark.usefixtures("clean_jobs")


def _events(cap: list[dict]) -> set[str]:
    return {entry["event"] for entry in cap}


@pytest.mark.asyncio
async def test_submit_and_cancel_emit_structured_logs(
    client: AsyncClient,
) -> None:
    with capture_logs() as cap:
        created = await client.post(
            "/jobs",
            json={"job_type": "email", "payload": {"to": "a@example.com"}},
        )
        assert created.status_code == 201
        job_id = created.json()["id"]
        cancelled = await client.post(f"/jobs/{job_id}/cancel")
        assert cancelled.status_code == 200

    events = _events(cap)
    assert "job_submitted" in events
    assert "job_enqueued" in events
    assert "job_cancelled" in events

    submitted = next(e for e in cap if e["event"] == "job_submitted")
    assert submitted["job_id"] == job_id
    assert submitted["job_type"] == "email"
    assert submitted["status"] == "pending"


@pytest.mark.asyncio
@patch("app.jobs.email.asyncio.sleep", new_callable=AsyncMock)
async def test_claim_and_complete_emit_structured_logs(
    _sleep: AsyncMock,
    client: AsyncClient,
) -> None:
    created = await client.post(
        "/jobs",
        json={"job_type": "email", "payload": {"to": "b@example.com"}},
    )
    job_id = created.json()["id"]

    queue = await QueueClient.connect()
    try:
        with capture_logs() as cap:
            assert await process_one(queue, worker_id="log-worker") is True
    finally:
        await queue.close()

    events = _events(cap)
    assert "job_claimed" in events
    assert "job_started" in events
    assert "job_completed" in events

    completed = next(e for e in cap if e["event"] == "job_completed")
    assert completed["job_id"] == job_id
    assert completed["status"] == "completed"


@pytest.mark.asyncio
@patch(
    "app.jobs.webhook.run",
    new_callable=AsyncMock,
    side_effect=HandlerError("boom"),
)
async def test_retry_fail_and_manual_retry_emit_structured_logs(
    _run: AsyncMock,
    client: AsyncClient,
) -> None:
    created = await client.post(
        "/jobs",
        json={"job_type": "webhook", "payload": {"url": "https://example.com"}},
    )
    job_id = created.json()["id"]

    queue = await QueueClient.connect()
    try:
        with capture_logs() as cap:
            assert await process_one(queue, worker_id="log-worker") is True
        assert "job_retry_scheduled" in _events(cap)
        retry = next(e for e in cap if e["event"] == "job_retry_scheduled")
        assert retry["job_id"] == job_id
        assert retry["attempt_count"] == 1
        assert "next_run_at" in retry

        # Last attempt → permanent failure.
        async with SessionLocal() as session:
            job = await session.get(Job, UUID(job_id))
            assert job is not None
            job.status = JobStatus.pending
            job.next_run_at = None
            job.attempt_count = 2
            job.max_attempts = 3
            await session.commit()
            await queue.enqueue(
                job.id, priority_score(job.priority, job.created_at)
            )

        with capture_logs() as cap:
            assert await process_one(queue, worker_id="log-worker") is True
        assert "job_failed" in _events(cap)
        failed = next(e for e in cap if e["event"] == "job_failed")
        assert failed["job_id"] == job_id
        assert failed["status"] == "failed"
        assert failed["error_message"] == "boom"
    finally:
        await queue.close()

    with capture_logs() as cap:
        response = await client.post(f"/jobs/{job_id}/retry")
        assert response.status_code == 200
    assert "job_manual_retry" in _events(cap)
