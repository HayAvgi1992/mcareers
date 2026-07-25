"""Pydantic request/response schemas for the jobs API."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)

from app.db.models import JobStatus, JobType

# Cap JSONB payload size to limit queue-poisoning DoS.
PAYLOAD_MAX_BYTES = 65_536 # 65KB
BATCH_MAX_ITEMS = 1_000


class EmailPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to: EmailStr


class WebhookPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: HttpUrl


class ReportPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="report", min_length=1, max_length=255)


class BatchPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[Any] = Field(max_length=BATCH_MAX_ITEMS)


_PAYLOAD_BY_TYPE: dict[JobType, type[BaseModel]] = {
    JobType.email: EmailPayload,
    JobType.webhook: WebhookPayload,
    JobType.report: ReportPayload,
    JobType.batch: BatchPayload,
}


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

    @model_validator(mode="after")
    def validate_payload_for_job_type(self) -> JobCreate:
        raw = json.dumps(self.payload, default=str).encode("utf-8")
        if len(raw) > PAYLOAD_MAX_BYTES:
            raise ValueError(
                f"payload must be at most {PAYLOAD_MAX_BYTES} bytes "
                f"(got {len(raw)})"
            )

        schema = _PAYLOAD_BY_TYPE[self.job_type]
        validated = schema.model_validate(self.payload)
        # Normalize (e.g. HttpUrl → str) so handlers see plain JSON.
        self.payload = validated.model_dump(mode="json")
        return self


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
