"""Job HTTP routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, get_queue
from app.api.schemas import JobCreate, JobResponse
from app.queue.client import QueueClient
from app.services import job_service
from app.services.job_service import JobConflictError, JobNotFoundError

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    body: JobCreate,
    session: AsyncSession = Depends(get_db),
    queue: QueueClient = Depends(get_queue),
) -> JobResponse:
    job = await job_service.submit_job(session, queue, body)
    return JobResponse.model_validate(job)


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
