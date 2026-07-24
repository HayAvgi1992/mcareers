"""Thin async Redis wrapper for the jobs dispatch ZSETs."""

from __future__ import annotations

import time
import uuid
from datetime import datetime
from typing import Self

from redis.asyncio import Redis

from app.config import settings
from app.queue.keys import JOBS_PENDING, JOBS_SCHEDULED


class QueueClient:
    """Redis dispatch helpers. Business rules live in services/worker."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    @classmethod
    async def connect(cls, url: str | None = None) -> Self:
        redis = Redis.from_url(url or settings.redis_url, decode_responses=True)
        await redis.ping()
        return cls(redis)

    async def enqueue(
        self, job_id: uuid.UUID, score: float, *, nx: bool = False
    ) -> bool:
        """Add job to pending ZSET. With nx=True, only if not already present."""
        added = await self._redis.zadd(
            JOBS_PENDING, {str(job_id): score}, nx=nx
        )
        return bool(added)

    async def schedule(self, job_id: uuid.UUID, run_at: datetime) -> bool:
        """Add job to scheduled ZSET. Score = run_at unix epoch seconds."""
        added = await self._redis.zadd(
            JOBS_SCHEDULED, {str(job_id): run_at.timestamp()}
        )
        return bool(added)

    async def dequeue(self) -> uuid.UUID | None:
        """Pop the highest-priority ready job ID (lowest ZSET score)."""
        items = await self._redis.zpopmin(JOBS_PENDING, count=1)
        if not items:
            return None
        job_id, _score = items[0]
        return uuid.UUID(job_id)

    async def due_scheduled(
        self, *, now: float | None = None, limit: int = 100
    ) -> list[uuid.UUID]:
        """Job IDs in jobs:scheduled with score <= now (due)."""
        score = time.time() if now is None else now
        members = await self._redis.zrangebyscore(
            JOBS_SCHEDULED, min="-inf", max=score, start=0, num=limit
        )
        return [uuid.UUID(m) for m in members]

    async def next_scheduled_score(self) -> float | None:
        """Earliest scheduled score, or None if the ZSET is empty."""
        items = await self._redis.zrange(JOBS_SCHEDULED, 0, 0, withscores=True)
        if not items:
            return None
        _member, score = items[0]
        return float(score)

    async def remove(self, job_id: uuid.UUID) -> None:
        """Best-effort remove from pending and scheduled ZSETs."""
        await self._redis.zrem(JOBS_PENDING, str(job_id))
        await self._redis.zrem(JOBS_SCHEDULED, str(job_id))

    async def remove_scheduled(self, job_id: uuid.UUID) -> None:
        await self._redis.zrem(JOBS_SCHEDULED, str(job_id))

    async def ping(self) -> bool:
        return bool(await self._redis.ping())

    async def close(self) -> None:
        await self._redis.aclose()
