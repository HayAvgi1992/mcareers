"""Unit tests for job handlers and registry (no DB/Redis)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.db.models import JobType
from app.jobs import batch, email, report, webhook
from app.jobs.base import HandlerError, UnknownJobTypeError
from app.jobs.registry import get_handler


def _job(job_type: JobType, payload: dict | None = None, job_id: uuid.UUID | None = None):
    return SimpleNamespace(
        id=job_id or uuid.uuid4(),
        job_type=job_type,
        payload=payload or {},
    )


@pytest.mark.asyncio
@patch("app.jobs.email.asyncio.sleep", new_callable=AsyncMock)
async def test_email_handler_returns_sent(mock_sleep: AsyncMock) -> None:
    result = await email.run(_job(JobType.email, {"to": "a@example.com"}))
    assert result["status"] == "sent"
    assert result["to"] == "a@example.com"
    assert result["message_id"].startswith("msg_")
    mock_sleep.assert_awaited()


@pytest.mark.asyncio
@patch("app.jobs.report.asyncio.sleep", new_callable=AsyncMock)
async def test_report_handler_returns_ready(mock_sleep: AsyncMock) -> None:
    result = await report.run(_job(JobType.report, {"name": "weekly"}))
    assert result["status"] == "ready"
    assert result["name"] == "weekly"
    assert result["download_url"] == "/reports/weekly.pdf"
    assert result["report_id"].startswith("rpt_")


@pytest.mark.asyncio
@patch("app.jobs.batch.asyncio.sleep", new_callable=AsyncMock)
async def test_batch_handler_counts_items(mock_sleep: AsyncMock) -> None:
    result = await batch.run(_job(JobType.batch, {"items": [1, 2, 3]}))
    assert result == {"status": "processed", "processed": 3, "failed": 0}


@pytest.mark.asyncio
@patch("app.jobs.webhook.asyncio.sleep", new_callable=AsyncMock)
async def test_webhook_success_path(mock_sleep: AsyncMock) -> None:
    # Find a job id that falls in the success bucket (~80%).
    for _ in range(200):
        job = _job(JobType.webhook, {"url": "https://example.com"})
        try:
            result = await webhook.run(job)
        except HandlerError:
            continue
        assert result["status"] == "delivered"
        assert result["status_code"] == 200
        assert result["url"] == "https://example.com"
        return
    pytest.fail("could not find a succeeding webhook job id")


@pytest.mark.asyncio
@patch("app.jobs.webhook.asyncio.sleep", new_callable=AsyncMock)
async def test_webhook_failure_path(mock_sleep: AsyncMock) -> None:
    for _ in range(200):
        job = _job(JobType.webhook, {"url": "https://example.com/fail"})
        try:
            await webhook.run(job)
        except HandlerError as exc:
            assert "webhook delivery failed" in str(exc)
            return
    pytest.fail("could not find a failing webhook job id")


@pytest.mark.asyncio
@patch("app.jobs.webhook.asyncio.sleep", new_callable=AsyncMock)
async def test_webhook_failure_rate_roughly_20_percent(mock_sleep: AsyncMock) -> None:
    failures = 0
    n = 500
    for _ in range(n):
        try:
            await webhook.run(_job(JobType.webhook, {"url": "https://example.com"}))
        except HandlerError:
            failures += 1
    rate = failures / n
    assert 0.10 <= rate <= 0.30


def test_registry_returns_known_handlers() -> None:
    assert get_handler(JobType.email) is email
    assert get_handler("webhook") is webhook
    assert get_handler(JobType.report) is report
    assert get_handler("batch") is batch


def test_registry_unknown_job_type() -> None:
    with pytest.raises(UnknownJobTypeError, match="unknown job_type"):
        get_handler("not_a_real_type")
