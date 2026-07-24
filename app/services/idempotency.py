"""Idempotency-key lookup and 24h cleanup."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job

IDEMPOTENCY_KEY_MAX_LEN = 255
IDEMPOTENCY_TTL = timedelta(hours=24)


class InvalidIdempotencyKeyError(ValueError):
    """Raised when an idempotency key fails validation."""


def normalize_idempotency_key(key: str | None) -> str | None:
    """Return a cleaned key, None if absent, or raise if invalid."""
    if key is None:
        return None
    cleaned = key.strip()
    if not cleaned:
        raise InvalidIdempotencyKeyError("idempotency key must not be empty")
    if len(cleaned) > IDEMPOTENCY_KEY_MAX_LEN:
        raise InvalidIdempotencyKeyError(
            f"idempotency key must be at most {IDEMPOTENCY_KEY_MAX_LEN} characters"
        )
    return cleaned


async def find_job_by_idempotency_key(
    session: AsyncSession, key: str
) -> Job | None:
    return await session.scalar(select(Job).where(Job.idempotency_key == key))

""" 
Cleanup expired idempotency keys from the database.

We currently dont have a background job to call this function to cleanup expired idempotency keys.
The idempotency keys are saved in the database and will be cleaned up when the job is processed or manually when needed
"""
async def cleanup_expired_idempotency_keys(
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> int:
    """
    Null out idempotency_key on jobs older than 24h so keys can be reused.
    Returns the number of rows updated.
    """
    cutoff = (now or datetime.now(UTC)) - IDEMPOTENCY_TTL
    result = await session.execute(
        update(Job)
        .where(
            Job.idempotency_key.is_not(None),
            Job.created_at < cutoff,
        )
        .values(idempotency_key=None)
    )
    await session.commit()
    return int(result.rowcount or 0)
