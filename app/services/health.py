"""Health check helpers — connectivity + queue/job/worker stats."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, JobStatus
from app.queue.client import QueueClient


async def check_database(session: AsyncSession) -> bool:
    try:
        await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def check_redis(queue: QueueClient) -> bool:
    try:
        return await queue.ping()
    except Exception:
        return False


async def job_counts_by_status(session: AsyncSession) -> dict[str, int]:
    """Return counts for every job_status, defaulting missing ones to 0."""
    rows = await session.execute(
        select(Job.status, func.count()).group_by(Job.status)
    )
    counts = {status.value: 0 for status in JobStatus}
    for status, count in rows.all():
        counts[status.value] = int(count)
    return counts


async def build_health_payload(
    session: AsyncSession,
    queue: QueueClient,
) -> tuple[dict, bool]:
    """
    Build health response body.
    Returns (payload, healthy) where healthy requires DB + Redis up.
    """
    db_ok = await check_database(session)
    redis_ok = await check_redis(queue)

    jobs = {status.value: 0 for status in JobStatus}
    if db_ok:
        jobs = await job_counts_by_status(session)

    queue_stats = {
        "pending_depth": None,
        "scheduled_depth": None,
        "dead_letter_depth": None,
    }
    workers: dict = {
        "alive_count": None,
        "alive": None,
    }
    if redis_ok:
        queue_stats = {
            "pending_depth": await queue.pending_depth(),
            "scheduled_depth": await queue.scheduled_depth(),
            "dead_letter_depth": await queue.dead_letter_depth(),
        }
        alive = await queue.list_alive_workers()
        workers = {
            "alive_count": len(alive),
            "alive": [
                {
                    "worker_id": worker_id,
                    "last_seen_at": datetime.fromtimestamp(
                        last_seen, tz=UTC
                    ).isoformat(),
                }
                for worker_id, last_seen in alive
            ],
        }

    healthy = db_ok and redis_ok
    payload = {
        "status": "ok" if healthy else "unavailable",
        "database": "ok" if db_ok else "error",
        "redis": "ok" if redis_ok else "error",
        "queue": queue_stats,
        "workers": workers,
        "jobs": {
            "pending": jobs["pending"],
            "processing": jobs["processing"],
            "failed": jobs["failed"],
            "scheduled": jobs["scheduled"],
            "completed": jobs["completed"],
            "cancelled": jobs["cancelled"],
        },
    }
    return payload, healthy
