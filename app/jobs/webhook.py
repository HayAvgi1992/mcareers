"""Mock webhook job handler — succeeds ~80%, fails ~20%."""

from __future__ import annotations

import asyncio
import random
from typing import Any

from app.db.models import Job
from app.jobs.base import HandlerError

_SLEEP_SECONDS = 0.3
_FAILURE_RATE = 0.2


async def run(job: Job) -> dict[str, Any]:
    await asyncio.sleep(_SLEEP_SECONDS)
    url = job.payload.get("url", "")
    # Deterministic per job id so retries of the same attempt are stable in tests.
    rng = random.Random(str(job.id))
    if rng.random() < _FAILURE_RATE:
        raise HandlerError(f"webhook delivery failed for url={url!r}")

    return {
        "status": "delivered",
        "url": url,
        "status_code": 200,
    }
