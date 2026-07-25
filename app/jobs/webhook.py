"""Mock webhook job handler — succeeds ~80%, fails ~20%."""

from __future__ import annotations

import asyncio
import random
from typing import Any

from app.config import settings
from app.db.models import Job
from app.jobs.base import HandlerError


async def run(job: Job) -> dict[str, Any]:
    await asyncio.sleep(settings.webhook_mock_sleep_seconds)
    url = job.payload.get("url")
    if not isinstance(url, str) or not url:
        raise HandlerError("webhook payload missing required field 'url'")
    # Deterministic per job id so retries of the same attempt are stable in tests.
    rng = random.Random(str(job.id))
    if rng.random() < 0.2:
        raise HandlerError(f"webhook delivery failed for url={url!r}")

    return {
        "status": "delivered",
        "url": url,
        "status_code": 200,
    }
