"""Mock email job handler."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from app.config import settings
from app.db.models import Job


async def run(job: Job) -> dict[str, Any]:
    await asyncio.sleep(settings.email_mock_sleep_seconds)
    to = job.payload.get("to", "unknown")
    return {
        "status": "sent",
        "to": to,
        "message_id": f"msg_{uuid.uuid4().hex[:12]}",
    }
