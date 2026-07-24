"""Job HTTP routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, get_queue
from app.api.schemas import (
    IdempotentJobResponse,
    JobCreate,
    JobListResponse,
    JobResponse,
)
from app.db.models import JobStatus, JobType
from app.queue.client import QueueClient
from app.services import job_service
from app.services.idempotency import InvalidIdempotencyKeyError
from app.services.job_service import JobConflictError, JobNotFoundError

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("")
async def create_job(
    body: JobCreate,
    session: AsyncSession = Depends(get_db),
    queue: QueueClient = Depends(get_queue),
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key")
    ] = None,
) -> JSONResponse:
    try:
        job, created = await job_service.submit_job(
            session, queue, body, idempotency_key=idempotency_key
        )
    except InvalidIdempotencyKeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from None # without traceback, clean error message

    if created:
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content=JobResponse.model_validate(job).model_dump(mode="json"),
        )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=IdempotentJobResponse(
            id=job.id, status=job.status
        ).model_dump(mode="json"),
    )


@router.get("", response_model=JobListResponse)
async def list_jobs(
    session: AsyncSession = Depends(get_db),
    status_filter: Annotated[
        JobStatus | None, Query(alias="status")
    ] = None,
    job_type: JobType | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JobListResponse:
    jobs, total = await job_service.list_jobs(
        session,
        status=status_filter,
        job_type=job_type,
        limit=limit,
        offset=offset,
    )
    return JobListResponse(
        items=[JobResponse.model_validate(j) for j in jobs],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{job_id}", response_model=JobResponse)
async def read_job(
    job_id: UUID,
    session: AsyncSession = Depends(get_db),
) -> JobResponse:
    job = await job_service.get_job(session, job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )
    return JobResponse.model_validate(job)


@router.post("/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(
    job_id: UUID,
    session: AsyncSession = Depends(get_db),
    queue: QueueClient = Depends(get_queue),
) -> JobResponse:
    try:
        job = await job_service.cancel_job(session, queue, job_id)
    except JobNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        ) from None
    except JobConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from None
    return JobResponse.model_validate(job)


@router.post("/{job_id}/retry", response_model=JobResponse)
async def retry_job(
    job_id: UUID,
    session: AsyncSession = Depends(get_db),
) -> JobResponse:
    try:
        job = await job_service.manual_retry(session, job_id)
    except JobNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        ) from None
    except JobConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from None
    return JobResponse.model_validate(job)
