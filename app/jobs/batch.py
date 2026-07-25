"""Mock batch processing handler — reports progress as items complete."""

from __future__ import annotations

import asyncio
from typing import Any

from app.db.models import Job
from app.jobs.base import ProgressReporter

_ITEM_SLEEP_SECONDS = 0.05


async def run(
    job: Job,
    report: ProgressReporter | None = None,
) -> dict[str, Any]:
    items = job.payload.get("items", [])
    if not isinstance(items, list):
        items = []

    total = len(items)
    if total == 0:
        if report is not None:
            await report(100)
        return {"status": "processed", "processed": 0, "failed": 0}

    for i, _item in enumerate(items):
        await asyncio.sleep(_ITEM_SLEEP_SECONDS)
        if report is not None:
            await report(int((i + 1) * 100 / total))

    return {
        "status": "processed",
        "processed": total,
        "failed": 0,
    }
