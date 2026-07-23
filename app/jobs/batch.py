"""Mock batch processing handler."""

from __future__ import annotations

import asyncio
from typing import Any

from app.db.models import Job

_SLEEP_SECONDS = 0.8


async def run(job: Job) -> dict[str, Any]:
    await asyncio.sleep(_SLEEP_SECONDS)
    items = job.payload.get("items", [])
    if not isinstance(items, list):
        items = []
    return {
        "status": "processed",
        "processed": len(items),
        "failed": 0,
    }
