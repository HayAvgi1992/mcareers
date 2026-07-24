"""Pydantic request/response schemas for the jobs API."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.models import JobStatus, JobType


class JobCreate(BaseModel):
    job_type: JobType
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(default=0, ge=-1000, le=1000)
    scheduled_at: datetime | None = None

    @field_validator("scheduled_at")
    @classmethod
    def scheduled_at_must_be_future(
        cls, value: datetime | None
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        if value <= datetime.now(UTC):
            raise ValueError("scheduled_at must be in the future")
        return value


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


class JobListResponse(BaseModel):
    items: list[JobResponse]
    total: int
    limit: int
    offset: int
