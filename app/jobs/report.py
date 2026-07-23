"""Mock report generation handler."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from app.db.models import Job

_SLEEP_SECONDS = 1.0


async def run(job: Job) -> dict[str, Any]:
    await asyncio.sleep(_SLEEP_SECONDS)
    name = job.payload.get("name", "report")
    return {
        "status": "ready",
        "report_id": f"rpt_{uuid.uuid4().hex[:12]}",
        "name": name,
        "download_url": f"/reports/{name}.pdf",
    }
