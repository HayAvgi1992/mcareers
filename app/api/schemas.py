"""Pydantic request/response schemas for the jobs API."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import JobStatus, JobType


class JobCreate(BaseModel):
    job_type: JobType
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(default=0, ge=-1000, le=1000)


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_type: JobType
    status: JobStatus
    priority: int
    payload: dict[str, Any]
    progress_pct: int
    attempt_count: int
    max_attempts: int
    result: dict[str, Any] | None = None
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    scheduled_at: datetime | None = None
    next_run_at: datetime | None = None


class IdempotentJobResponse(BaseModel):
    """Duplicate submission response — id and status only."""

    id: UUID
    status: JobStatus
