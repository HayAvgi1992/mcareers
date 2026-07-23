"""Mock email job handler."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from app.db.models import Job

# Simulated send latency (keep short enough for local demos).
_SLEEP_SECONDS = 0.5


async def run(job: Job) -> dict[str, Any]:
    await asyncio.sleep(_SLEEP_SECONDS)
    to = job.payload.get("to", "unknown")
    return {
        "status": "sent",
        "to": to,
        "message_id": f"msg_{uuid.uuid4().hex[:12]}",
    }
