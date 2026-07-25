"""Persist job lifecycle events to job_logs (DB audit trail)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import JobLog, LogLevel


async def append_job_log(
    session: AsyncSession,
    job_id: UUID,
    message: str,
    *,
    level: LogLevel = LogLevel.info,
    metadata: dict[str, Any] | None = None,
) -> JobLog:
    """
    Stage a job_logs row on the session. Caller commits.
    Do not put secrets or full payloads in metadata.
    """
    entry = JobLog(
        job_id=job_id,
        level=level,
        message=message,
        metadata_=metadata,
    )
    session.add(entry)
    return entry
