"""Mock report generation handler."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from app.config import settings
from app.db.models import Job


async def run(job: Job) -> dict[str, Any]:
    await asyncio.sleep(settings.report_mock_sleep_seconds)
    name = job.payload.get("name", "report")
    return {
        "status": "ready",
        "report_id": f"rpt_{uuid.uuid4().hex[:12]}",
        "name": name,
        "download_url": f"/reports/{name}.pdf",
    }
