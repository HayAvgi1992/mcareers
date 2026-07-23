"""Thin async Redis wrapper for the jobs dispatch ZSET."""

from __future__ import annotations

import uuid
from typing import Self

from redis.asyncio import Redis

from app.config import settings
from app.queue.keys import JOBS_PENDING


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

    async def dequeue(self) -> uuid.UUID | None:
        """Pop the highest-priority ready job ID (lowest ZSET score)."""
        items = await self._redis.zpopmin(JOBS_PENDING, count=1) # pop the highest-priority ready job ID (lowest ZSET score) and remove it from the queue
        if not items:
            return None
        job_id, _score = items[0]
        return uuid.UUID(job_id)

    async def remove(self, job_id: uuid.UUID) -> None:
        await self._redis.zrem(JOBS_PENDING, str(job_id))

    async def ping(self) -> bool:
        return bool(await self._redis.ping())

    async def close(self) -> None:
        await self._redis.aclose()
