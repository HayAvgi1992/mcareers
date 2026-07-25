"""Mock email job handler."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from app.config import settings
from app.db.models import Job
from app.jobs.base import HandlerError


async def run(job: Job) -> dict[str, Any]:
    await asyncio.sleep(settings.email_mock_sleep_seconds)
    to = job.payload.get("to")
    if not isinstance(to, str) or not to:
        raise HandlerError("email payload missing required field 'to'")
    return {
        "status": "sent",
        "to": to,
        "message_id": f"msg_{uuid.uuid4().hex[:12]}",
    }
