"""Health + queue stats endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, get_queue
from app.queue.client import QueueClient
from app.services.health import build_health_payload

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(
    session: AsyncSession = Depends(get_db),
    queue: QueueClient = Depends(get_queue),
) -> JSONResponse:
    payload, healthy = await build_health_payload(session, queue)
    return JSONResponse(
        status_code=200 if healthy else 503,
        content=payload,
    )
